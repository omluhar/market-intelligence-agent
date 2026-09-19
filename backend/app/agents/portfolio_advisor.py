import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from backend.app.agents.scout_agent import run_scout
from backend.app.agents.tactical_agent import run_tactical
from backend.app.config import settings
from backend.app.services.market_cache import EMPTY_TECHNICAL, cached_snapshot, cached_history_bundle

logger = logging.getLogger(__name__)

ROTH_PROMPT = """You advise on a Roth IRA portfolio. Goals: long-term compound growth, capital preservation,
low turnover, tax-free compounding. Prefer quality compounders, broad ETFs, dividend growers. Avoid frequent
trading and speculative momentum. Single-stock concentration above 15% warrants a trim discussion.
Hold periods should be measured in years."""

TAXABLE_PROMPT = """You advise on a taxable brokerage account. Goals: solid long-term growth with slightly more
flexibility than a Roth, but still relatively safe. Favor quality at reasonable prices, allow modest tactical
tilts when risk/reward is favorable. Consider tax efficiency (avoid unnecessary churn). Single-stock concentration
above 20% warrants review. Shorter holds are acceptable when fundamentals deteriorate or targets are hit."""

SYSTEM_PROMPT = """You are the Portfolio Advisor for Market Intelligence Council.

You receive live holdings (quantity, average cost, current price, unrealized P/L) plus Scout and Tactical
signals for each symbol. Produce actionable guidance tailored to each account's goal. You do NOT place trades.

Output JSON with an "insights" array. Each insight needs:
- account_id (string)
- account_type (roth_ira | taxable | traditional_ira | other)
- symbol (string or null for portfolio-level / rebalancing insight)
- priority (high | medium | low)
- action (HOLD | TRIM | ADD | REVIEW | REBALANCE | WATCH)
- title (short headline)
- body (2-5 sentences referencing the user's cost basis vs current price when relevant)
- target_price (number or null): suggested limit/stop reference price when ADD/TRIM/WATCH
- suggested_size (string or null): e.g. "Trim 10 shares", "Add $500", "Move $2,000 cash to VTI in Roth"

Rules:
- Roth IRA: prioritize hold/compound; trim only on concentration or broken thesis.
- Taxable: allow tactical trims/adds when signals align; mention tax awareness without inventing tax lots.
- Use provided average_cost and current_price — compare them explicitly in body when advising ADD/TRIM.
- Include at least one REBALANCE insight (symbol null) comparing cash vs invested across accounts.
- Include per-holding insights for positions above 5% of total portfolio weight when action is not HOLD.
- Never invent prices; use provided data and round to sensible decimals.
- Maximum 15 insights total.
"""


class PortfolioInsight(BaseModel):
    account_id: str
    account_type: str
    symbol: Optional[str] = None
    priority: str = "medium"
    action: str = "REVIEW"
    title: str
    body: str
    target_price: Optional[float] = None
    suggested_size: Optional[str] = None


class PortfolioAdvice(BaseModel):
    insights: List[PortfolioInsight] = Field(default_factory=list)
    summary: str = ""


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.2,
        api_key=settings.OPENAI_API_KEY or None,
    )


def _research_symbol(symbol: str) -> Dict[str, Any]:
    ticker = symbol.upper().strip()
    try:
        snapshot = cached_snapshot(ticker)
        bundle = cached_history_bundle(ticker)
        technical = bundle.get("technical") or dict(EMPTY_TECHNICAL)
        last_price = float(snapshot.get("last_price") or technical.get("last_price") or 0)
        scout = run_scout(snapshot)
        tactical = run_tactical(ticker, last_price, technical)
        return {
            "symbol": ticker,
            "snapshot": snapshot,
            "technical": technical,
            "scout_action": scout.action if scout else None,
            "scout_thesis": scout.thesis if scout else None,
            "tactical_action": tactical.action if tactical else None,
            "tactical_rationale": tactical.rationale if tactical else None,
            "tactical_target": tactical.target_price if tactical else None,
            "tactical_stop": tactical.stop_loss if tactical else None,
        }
    except Exception as exc:
        logger.warning("Portfolio research failed for %s: %s", ticker, exc)
        return {"symbol": ticker, "error": str(exc)}


def analyze_portfolio(dashboard: Dict[str, Any]) -> Dict[str, Any]:
    accounts = dashboard.get("accounts") or []
    holdings = dashboard.get("holdings") or []
    if not holdings and not any(float(a.get("cash_balance") or 0) > 0 for a in accounts):
        return {
            "summary": "Connect Robinhood or add holdings to receive tailored portfolio guidance.",
            "insights": [],
            "research": [],
        }

    symbols = sorted({str(h["symbol"]).upper() for h in holdings if h.get("symbol")})
    research = [_research_symbol(symbol) for symbol in symbols[:20]]

    holdings_payload = []
    for holding in holdings:
        market_value = float(holding.get("market_value") or 0)
        total = float(dashboard.get("total_value") or 1)
        avg_cost = float(holding.get("average_cost") or 0)
        current_price = float(holding.get("current_price") or 0)
        weight_pct = round((market_value / total) * 100, 2) if total > 0 else 0
        pct_from_cost = round(((current_price - avg_cost) / avg_cost) * 100, 2) if avg_cost > 0 else None
        holdings_payload.append(
            {
                "account_id": holding.get("account_id"),
                "account_name": holding.get("account_name"),
                "account_type": holding.get("account_type"),
                "symbol": holding.get("symbol"),
                "quantity": holding.get("quantity"),
                "average_cost": avg_cost,
                "current_price": current_price,
                "market_value": market_value,
                "unrealized_pnl": holding.get("unrealized_pnl"),
                "weight_pct": weight_pct,
                "pct_gain_from_cost_basis": pct_from_cost,
            }
        )

    accounts_payload = []
    goals = []
    for account in accounts:
        acct_type = str(account.get("account_type") or "other")
        cash = float(account.get("cash_balance") or 0)
        positions = float(account.get("positions_value") or 0)
        accounts_payload.append(
            {
                "id": account.get("id"),
                "name": account.get("name"),
                "account_type": acct_type,
                "cash_balance": cash,
                "positions_value": positions,
                "total_value": round(cash + positions, 2),
                "buying_power": account.get("buying_power"),
            }
        )
        if acct_type == "roth_ira":
            goals.append(f"{account.get('name')}: {ROTH_PROMPT}")
        elif acct_type == "taxable":
            goals.append(f"{account.get('name')}: {TAXABLE_PROMPT}")

    payload = {
        "account_goals": goals,
        "accounts": accounts_payload,
        "total_value": dashboard.get("total_value"),
        "value_by_account_type": dashboard.get("value_by_account_type"),
        "holdings": holdings_payload,
        "symbol_research": research,
    }

    structured = _get_llm().with_structured_output(PortfolioAdvice)
    advice = structured.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(payload, default=str)[:16000]),
        ]
    )
    if isinstance(advice, dict):
        advice = PortfolioAdvice.model_validate(advice)

    insights = [item.model_dump() for item in advice.insights]
    return {
        "summary": advice.summary,
        "insights": insights,
        "research": research,
    }
