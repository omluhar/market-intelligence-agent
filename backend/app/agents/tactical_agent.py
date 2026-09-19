from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

from backend.app.agents.risk_guardian import TradeProposal
from backend.app.config import settings


class TacticalProposal(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL", "SHORT_PASS"]
    target_price: float
    stop_loss: float
    time_horizon: Literal["SHORT_TERM"] = "SHORT_TERM"
    setup_type: Literal["MOMENTUM_BREAKOUT", "PULLBACK_BUY", "PROFIT_TAKE"] = "MOMENTUM_BREAKOUT"
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


def _round_px(value: float) -> float:
    return round(float(value), 4)


def run_tactical(
    symbol: str,
    last_price: float,
    technical: Dict[str, Any],
    portfolio_context: Optional[Dict[str, Any]] = None,
) -> Optional[TacticalProposal]:
    """Deterministic short-horizon momentum node. LLM is not required for triggers."""
    ticker = symbol.upper().strip()
    price = float(last_price or 0.0)
    rsi = technical.get("rsi_14")
    sma_50 = technical.get("sma_50")
    sma_200 = technical.get("sma_200")
    volume_surge = technical.get("volume_surge_ratio")
    trend = technical.get("trend") or "NEUTRAL"
    golden_cross = bool(technical.get("golden_cross"))
    drawdown = technical.get("drawdown_from_high_pct")
    weight_pct = None
    if portfolio_context:
        try:
            weight_pct = float(portfolio_context.get("weight_pct"))
        except (TypeError, ValueError):
            weight_pct = None

    if price <= 0 or rsi is None or sma_50 is None:
        return None

    rsi_v = float(rsi)
    sma_50_v = float(sma_50)
    sma_200_v = float(sma_200) if sma_200 is not None else None
    surge_v = float(volume_surge) if volume_surge is not None else None

    if rsi_v > 75 or (weight_pct is not None and weight_pct > 22 and rsi_v > 68):
        stretch = min(0.35, max(0.0, (rsi_v - 75.0) / 50.0))
        setup = "PROFIT_TAKE" if weight_pct and weight_pct > 22 else "MOMENTUM_BREAKOUT"
        trim_note = (
            f" Position is {weight_pct:.1f}% of portfolio; consider trimming concentration."
            if weight_pct and weight_pct > 22
            else ""
        )
        return TacticalProposal(
            symbol=ticker,
            action="SELL",
            setup_type=setup,
            target_price=_round_px(price * 0.94),
            stop_loss=_round_px(price * 1.03),
            confidence=round(min(0.95, 0.62 + stretch), 4),
            rationale=(
                f"RSI-14 at {rsi_v:.1f} is overbought (>75). "
                f"Fade the extension with a 6% downside target and a 3% stop above entry.{trim_note}"
            ),
        )

    if sma_200_v is not None and price < sma_200_v:
        return TacticalProposal(
            symbol=ticker,
            action="SHORT_PASS",
            target_price=_round_px(price),
            stop_loss=_round_px(price * 0.97),
            confidence=0.55,
            rationale=(
                f"Price ${price:.2f} is below the 200-day SMA ${sma_200_v:.2f}. "
                "No long-momentum setup; sandbox does not open a short here."
            ),
        )

    pullback_ready = (
        sma_200_v is not None
        and price > sma_200_v
        and 30.0 <= rsi_v <= 45.0
        and trend in ("BULLISH", "NEUTRAL")
    )
    if pullback_ready:
        confidence = 0.58
        if golden_cross:
            confidence += 0.10
        if drawdown is not None and float(drawdown) < -8:
            confidence += 0.08
        return TacticalProposal(
            symbol=ticker,
            action="BUY",
            setup_type="PULLBACK_BUY",
            target_price=_round_px(price * 1.05),
            stop_loss=_round_px(price * 0.96),
            confidence=round(min(0.9, confidence), 4),
            rationale=(
                f"Pullback setup: RSI-14 {rsi_v:.1f} cooled off while price remains above the 200-day SMA "
                f"(${sma_200_v:.2f}). Look for a controlled bounce with a 5% target and 4% stop."
            ),
        )

    buy_ready = (
        35.0 <= rsi_v <= 65.0
        and price > sma_50_v
        and surge_v is not None
        and surge_v > 1.2
    )
    if not buy_ready:
        return None

    if weight_pct is not None and weight_pct > 18:
        return None

    confidence = 0.62
    if trend == "BULLISH":
        confidence += 0.12
    if surge_v is not None and surge_v > 1.5:
        confidence += 0.10
    if 45.0 <= rsi_v <= 55.0:
        confidence += 0.08
    if golden_cross:
        confidence += 0.06

    return TacticalProposal(
        symbol=ticker,
        action="BUY",
        setup_type="MOMENTUM_BREAKOUT",
        target_price=_round_px(price * 1.06),
        stop_loss=_round_px(price * 0.97),
        confidence=round(min(0.95, confidence), 4),
        rationale=(
            f"Momentum breakout: RSI-14 {rsi_v:.1f} is mid-range, price is above the 50-day SMA "
            f"(${sma_50_v:.2f}), and volume is {surge_v:.2f}x the 20-day average. "
            "Target +6% / stop -3% on a short-term swing."
        ),
    )


def tactical_to_trade_proposal(
    tactical: TacticalProposal,
    last_price: float,
) -> Optional[TradeProposal]:
    if tactical.action not in ("BUY", "SELL"):
        return None
    entry = float(last_price or 0.0)
    if entry <= 0:
        return None
    shares = int(settings.MAX_POSITION_SIZE_USD // entry)
    if shares < 1:
        return None
    return TradeProposal(
        symbol=tactical.symbol,
        action=tactical.action,
        target_price=_round_px(entry),
        shares=shares,
        total_value=round(shares * entry, 2),
        thesis=tactical.rationale
        or f"{tactical.setup_type} {tactical.time_horizon} {tactical.action}",
    )
