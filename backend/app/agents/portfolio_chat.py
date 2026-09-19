import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from backend.app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Portfolio Advisor chat for a read-only Robinhood sync (via SnapTrade).

You see the user's real account balances, holdings (quantity, average cost, current price, unrealized P/L),
and any recent tailored insights. You do NOT place trades or move money — you advise only.

When recommending action:
- Reference their actual average cost vs current price.
- Give concrete sizing when possible (shares or dollar amount), staying conservative.
- For Roth IRA: long-term compound growth, low turnover, tax-free context.
- For taxable brokerage: quality growth, tax-aware (avoid unnecessary churn).
- For crypto account: note higher volatility; keep allocation sensible vs total net worth.
- For rebalancing: compare cash vs invested across accounts and suggest shifts in plain English.

Be concise (2-8 sentences unless the user asks for detail). Do not invent holdings or prices.
If data is missing, say what to sync or analyze first."""


class PortfolioChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class PortfolioChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: List[PortfolioChatTurn] = Field(default_factory=list)


class PortfolioChatResponse(BaseModel):
    reply: str


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.25,
        api_key=settings.OPENAI_API_KEY or None,
    )


def _dashboard_context(dashboard: Dict[str, Any]) -> Dict[str, Any]:
    accounts = []
    for account in dashboard.get("accounts") or []:
        cash = float(account.get("cash_balance") or 0)
        positions = float(account.get("positions_value") or 0)
        accounts.append(
            {
                "id": account.get("id"),
                "name": account.get("name"),
                "account_type": account.get("account_type"),
                "cash_balance": cash,
                "positions_value": positions,
                "total_value": round(cash + positions, 2),
                "buying_power": account.get("buying_power"),
            }
        )

    holdings = []
    for holding in dashboard.get("holdings") or []:
        holdings.append(
            {
                "account_name": holding.get("account_name"),
                "account_type": holding.get("account_type"),
                "symbol": holding.get("symbol"),
                "quantity": holding.get("quantity"),
                "average_cost": holding.get("average_cost"),
                "current_price": holding.get("current_price"),
                "market_value": holding.get("market_value"),
                "unrealized_pnl": holding.get("unrealized_pnl"),
            }
        )

    insights = []
    for insight in (dashboard.get("insights") or [])[:12]:
        insights.append(
            {
                "title": insight.get("title"),
                "action": insight.get("action"),
                "symbol": insight.get("symbol"),
                "body": insight.get("body"),
                "target_price": insight.get("target_price"),
                "suggested_size": insight.get("suggested_size"),
                "account_type": insight.get("account_type"),
            }
        )

    return {
        "total_value": dashboard.get("total_value"),
        "value_by_account_type": dashboard.get("value_by_account_type"),
        "analysis_summary": dashboard.get("analysis_summary"),
        "accounts": accounts,
        "holdings": holdings,
        "recent_insights": insights,
    }


def answer_portfolio_question(req: PortfolioChatRequest, dashboard: Dict[str, Any]) -> str:
    trimmed = req.history[-8:]
    transcript = "\n".join(f"{turn.role}: {turn.content}" for turn in trimmed)
    payload = {
        "question": req.message.strip(),
        "recent_chat": transcript,
        "portfolio": _dashboard_context(dashboard),
    }
    response = _get_llm().invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(payload, default=str)[:16000]),
        ]
    )
    content = getattr(response, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts = [str(item.get("text", item)) for item in content if item]
        return "\n".join(parts).strip()
    return "I could not generate a reply. Try asking about a specific holding or account rebalance."
