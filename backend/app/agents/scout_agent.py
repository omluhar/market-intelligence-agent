import json
import logging
from typing import Any, Dict, Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError

from backend.app.agents.risk_guardian import TradeProposal
from backend.app.collectors.price_collector import MarketSnapshot
from backend.app.config import settings

logger = logging.getLogger(__name__)

_SCOUT_GRAPH = None

SYSTEM_PROMPT = """You are the Scout agent on a multi-agent equity trading desk.

Your only job is to inspect a market snapshot and decide whether a trade setup
exists. You must check valuation using PE and debt-to-equity before proposing.

Valuation rules:
- Prefer names with trailing PE below 25, or forward PE below 20.
- Treat debt-to-equity above 10 as a yfinance percentage (150 means 1.50).
  Acceptable leverage is generally at or below 2.0 on a ratio basis.
- A setup passes only when BOTH valuation (PE) and leverage (debt-to-equity)
  are acceptable, or when missing one metric is clearly offset by the other
  plus a discounted 52-week price. If the picture is mixed or expensive,
  valuation_pass must be false.
- If valuation_pass is false, leave action/shares/target_price/thesis empty.
- If valuation_pass is true, propose BUY for undervalued names or SELL for
  rich/over-levered names. action must be exactly BUY or SELL.
- Size the order so shares * target_price does not exceed
  MAX_POSITION_SIZE_USD. Use last_price as target_price unless you have a
  specific limit. shares must be an integer >= 1.
"""


class ScoutDecision(BaseModel):
    valuation_pass: bool = Field(
        description="True only if PE and debt-to-equity support a trade setup"
    )
    pe_assessment: str = Field(description="Assessment of trailing and/or forward PE")
    debt_assessment: str = Field(description="Assessment of debt-to-equity")
    action: Optional[str] = Field(
        default=None,
        description="BUY or SELL if a setup exists; otherwise omit",
    )
    shares: Optional[int] = Field(
        default=None,
        description="Positive share count if proposing a trade",
    )
    target_price: Optional[float] = Field(
        default=None,
        description="Limit/target price, typically last_price",
    )
    thesis: Optional[str] = Field(
        default=None,
        description="Short investment thesis if proposing a trade",
    )


class ScoutState(TypedDict):
    snapshot: MarketSnapshot
    decision: Optional[ScoutDecision]
    proposal: Optional[TradeProposal]


def _normalize_debt_to_equity(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    # yfinance frequently reports D/E as a percentage (e.g. 150.2).
    if value > 10:
        return round(value / 100.0, 4)
    return value


def _llm_payload(snapshot: MarketSnapshot) -> Dict[str, Any]:
    return {
        "symbol": snapshot.get("symbol"),
        "last_price": snapshot.get("last_price"),
        "market_cap": snapshot.get("market_cap"),
        "fifty_two_week_high": snapshot.get("fifty_two_week_high"),
        "fifty_two_week_low": snapshot.get("fifty_two_week_low"),
        "trailing_pe": snapshot.get("trailing_pe"),
        "forward_pe": snapshot.get("forward_pe"),
        "debt_to_equity_raw": snapshot.get("debt_to_equity"),
        "normalized_debt_to_equity": _normalize_debt_to_equity(
            snapshot.get("debt_to_equity")
        ),
        "free_cashflow": snapshot.get("free_cashflow"),
        "MAX_POSITION_SIZE_USD": settings.MAX_POSITION_SIZE_USD,
    }


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=settings.OPENAI_API_KEY or None,
    )


def analyze_valuation(state: ScoutState) -> Dict[str, Any]:
    snapshot = state["snapshot"]
    last_price = float(snapshot.get("last_price") or 0.0)
    if last_price <= 0:
        logger.info("Scout skip: missing last_price for %s", snapshot.get("symbol"))
        return {
            "decision": ScoutDecision(
                valuation_pass=False,
                pe_assessment="No last price available; cannot value the name.",
                debt_assessment="Skipped because price data is missing.",
            ),
            "proposal": None,
        }

    structured_llm = _get_llm().with_structured_output(ScoutDecision)
    decision = structured_llm.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(_llm_payload(snapshot), default=str)),
        ]
    )
    if isinstance(decision, dict):
        decision = ScoutDecision.model_validate(decision)
    return {"decision": decision}


def emit_proposal(state: ScoutState) -> Dict[str, Any]:
    decision = state.get("decision")
    snapshot = state["snapshot"]
    if decision is None or not decision.valuation_pass:
        return {"proposal": None}
    if decision.action is None or decision.shares is None or decision.target_price is None:
        return {"proposal": None}

    try:
        shares = int(decision.shares)
        target_price = float(decision.target_price)
        proposal = TradeProposal(
            symbol=str(snapshot["symbol"]).upper(),
            action=str(decision.action).upper(),
            target_price=target_price,
            shares=shares,
            total_value=round(shares * target_price, 2),
            thesis=decision.thesis
            or f"{decision.pe_assessment} {decision.debt_assessment}".strip(),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        logger.info("Scout proposal failed TradeProposal validation: %s", exc)
        return {"proposal": None}

    if proposal.shares < 1 or proposal.total_value <= 0:
        return {"proposal": None}
    return {"proposal": proposal}


def build_scout_graph():
    workflow = StateGraph(ScoutState)
    workflow.add_node("analyze_valuation", analyze_valuation)
    workflow.add_node("emit_proposal", emit_proposal)
    workflow.set_entry_point("analyze_valuation")
    workflow.add_edge("analyze_valuation", "emit_proposal")
    workflow.add_edge("emit_proposal", END)
    return workflow.compile()


def get_scout_graph():
    global _SCOUT_GRAPH
    if _SCOUT_GRAPH is None:
        _SCOUT_GRAPH = build_scout_graph()
    return _SCOUT_GRAPH


def run_scout(snapshot: MarketSnapshot) -> Optional[TradeProposal]:
    """Evaluate a market snapshot and return a TradeProposal, or None."""
    result = get_scout_graph().invoke(
        {"snapshot": snapshot, "decision": None, "proposal": None}
    )
    proposal = result.get("proposal")
    if proposal is None:
        return None
    if isinstance(proposal, TradeProposal):
        return proposal
    return TradeProposal.model_validate(proposal)
