from pydantic import BaseModel, Field
from backend.app.config import settings

class TradeProposal(BaseModel):
    symbol: str
    action: str = Field(pattern="^(BUY|SELL)$")
    target_price: float
    shares: int
    total_value: float
    thesis: str

class RiskEvaluation(BaseModel):
    approved: bool
    adjusted_shares: int
    adjusted_total_value: float
    reason: str

def evaluate_trade(proposal: TradeProposal, current_cash: float) -> RiskEvaluation:
    if proposal.action == "SELL":
        return RiskEvaluation(
            approved=True,
            adjusted_shares=proposal.shares,
            adjusted_total_value=proposal.total_value,
            reason="Sell orders reduce open market risk."
        )

    max_allowed_spend = min(
        settings.MAX_POSITION_SIZE_USD,
        current_cash * settings.MAX_PORTFOLIO_RISK_PCT
    )

    if proposal.total_value <= max_allowed_spend:
        return RiskEvaluation(
            approved=True,
            adjusted_shares=proposal.shares,
            adjusted_total_value=proposal.total_value,
            reason="Trade strictly adheres to max position and portfolio risk bounds."
        )

    capped_shares = int(max_allowed_spend // proposal.target_price)
    if capped_shares < 1:
        return RiskEvaluation(
            approved=False,
            adjusted_shares=0,
            adjusted_total_value=0.0,
            reason=f"Position value exceeds risk limit of ${max_allowed_spend:.2f}; cannot buy even 1 full share."
        )

    return RiskEvaluation(
        approved=True,
        adjusted_shares=capped_shares,
        adjusted_total_value=capped_shares * proposal.target_price,
        reason=f"Position downsized from {proposal.shares} to {capped_shares} to meet ${max_allowed_spend:.2f} risk cap."
    )
