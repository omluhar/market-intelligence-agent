import logging
from typing import Any, Dict, List, Optional

from backend.app.agents.risk_guardian import RiskEvaluation, evaluate_trade
from backend.app.agents.scout_agent import run_scout
from backend.app.agents.tactical_agent import run_tactical, tactical_to_trade_proposal
from backend.app.collectors.news_collector import fetch_ticker_news
from backend.app.collectors.price_collector import fetch_market_snapshot
from backend.app.collectors.technical_collector import fetch_technical_snapshot
from backend.app.config import settings
from backend.app.execution.sandbox_router import execute_order, save_recommendation

logger = logging.getLogger(__name__)

EMPTY_TECHNICAL: Dict[str, Any] = {
    "sma_50": None,
    "sma_200": None,
    "rsi_14": None,
    "volume_surge_ratio": None,
    "trend": "NEUTRAL",
    "last_price": 0.0,
    "drawdown_from_high_pct": None,
    "golden_cross": None,
}


def _short_pass_risk() -> Dict[str, Any]:
    return RiskEvaluation(
        approved=False,
        adjusted_shares=0,
        adjusted_total_value=0.0,
        reason="Tactical SHORT_PASS: no executable long or short in the paper sandbox.",
    ).model_dump()


def evaluate_symbol(
    ticker: str,
    *,
    include_news: bool = True,
    persist: bool = True,
    execute: bool = True,
    source: str = "SCAN",
) -> Dict[str, Any]:
    symbol = ticker.upper().strip()
    snapshot = fetch_market_snapshot(symbol)
    news: List[Dict[str, Any]] = fetch_ticker_news(symbol) if include_news else []

    try:
        technical = fetch_technical_snapshot(symbol)
    except Exception as exc:
        logger.warning("Technical snapshot failed for %s: %s", symbol, exc)
        technical = dict(EMPTY_TECHNICAL)

    last_price = float(snapshot.get("last_price") or technical.get("last_price") or 0.0)

    proposal = run_scout(snapshot)
    tactical = run_tactical(symbol, last_price, technical)

    scout_risk = None
    tactical_risk = None
    scout_order = None
    tactical_order = None

    if proposal:
        if persist:
            save_recommendation(
                {
                    "symbol": proposal.symbol,
                    "horizon": "LONG_TERM_VALUE",
                    "action": proposal.action,
                    "target_price": proposal.target_price,
                    "trailing_pe": snapshot.get("trailing_pe"),
                    "forward_pe": snapshot.get("forward_pe"),
                    "thesis": proposal.thesis,
                    "source": source,
                }
            )
        scout_risk = evaluate_trade(proposal, current_cash=settings.PAPER_CASH_USD)
        if execute and scout_risk.approved:
            scout_order = execute_order(proposal, scout_risk, is_dry_run=settings.DRY_RUN)

    if tactical:
        if persist:
            save_recommendation(
                {
                    "symbol": tactical.symbol,
                    "horizon": "SHORT_TERM_MOMENTUM",
                    "action": tactical.action,
                    "target_price": tactical.target_price,
                    "trailing_pe": snapshot.get("trailing_pe"),
                    "forward_pe": snapshot.get("forward_pe"),
                    "thesis": tactical.rationale,
                    "source": source,
                }
            )
        trade = tactical_to_trade_proposal(tactical, last_price)
        if trade:
            tactical_risk = evaluate_trade(trade, current_cash=settings.PAPER_CASH_USD)
            if execute and tactical_risk.approved:
                tactical_order = execute_order(trade, tactical_risk, is_dry_run=settings.DRY_RUN)
        else:
            tactical_risk = RiskEvaluation.model_validate(_short_pass_risk())

    message = _compose_message(proposal, tactical, scout_risk, tactical_risk)
    return {
        "ticker": symbol,
        "snapshot": snapshot,
        "technical": technical,
        "news": news,
        "proposal": proposal.model_dump() if proposal else None,
        "tactical": tactical.model_dump() if tactical else None,
        "risk": scout_risk.model_dump() if scout_risk else None,
        "tactical_risk": tactical_risk.model_dump() if tactical_risk else None,
        "order": scout_order,
        "tactical_order": tactical_order,
        "dry_run": settings.DRY_RUN,
        "message": message,
    }


def _compose_message(
    proposal,
    tactical,
    scout_risk: Optional[Any],
    tactical_risk: Optional[Any],
) -> str:
    if proposal is None and tactical is None:
        return "No trade setup passed scout valuation or tactical momentum filters."
    parts: List[str] = []
    if proposal and scout_risk:
        parts.append(
            f"Scout {proposal.action} {'approved' if scout_risk.approved else 'vetoed'}."
        )
    elif proposal is None:
        parts.append("Scout found no long-horizon setup.")
    if tactical and tactical_risk:
        parts.append(
            f"Tactical {tactical.action} {'approved' if tactical_risk.approved else 'held'}."
        )
    elif tactical is None:
        parts.append("Tactical found no short-horizon setup.")
    return " ".join(parts)
