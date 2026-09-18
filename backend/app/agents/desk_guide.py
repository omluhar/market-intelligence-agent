import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from backend.app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the desk guide for Market Intelligence Council, a paper-trading sandbox.

Explain the interface in plain English. Be concise (usually 2-6 sentences). Use the provided
live context when the user asks about the current ticker, numbers, or cards. Do not invent
prices or ratios that are not in the context. Do not claim this is live brokerage.

What the screen shows:
- Watchlist: names you follow. Clicking one loads quotes/charts only. It does not trade.
- Scan: runs the council (Scout + Tactical + Risk Guardian) and may record a simulated order.
- Trigger Sweep: background scan of the watchlist plus a discovery universe.
- L1 Telemetry: last price, 52-week range, market cap, and fundamental/technical ratios.
- Chart candles: each candle is one time bucket (open/high/low/close). Interval chips change the bucket size (5m, 15m, 1H, 1D, 1W, 1M).
- Trailing/Forward P/E: price vs earnings (past 12 months vs expected). Lower can mean cheaper, not always better.
- Debt/Equity: leverage. Yahoo often reports it as a percent (150 ≈ 1.50).
- Free Cash Flow: cash after operations and capex.
- SMA 50 / SMA 200: 50-day and 200-day average prices. Golden cross = 50 above 200.
- RSI 14: 0-100 momentum. ~70 overbought, ~30 oversold. Tactical buys prefer 35-65.
- Vol Surge: today's volume vs the 20-day average (>1.2x is a surge).
- Fundamental Scout: slower valuation agent (P/E, debt). Long-horizon idea.
- Tactical Momentum: short-term rules (RSI, trend, volume). Target/stop are swing levels.
- Risk Guardian: hard caps on position size. APPROVED/VETOED is the sandbox risk check.
- AI Opportunity Screener: saved ideas from scans/sweeps (long-term vs short-term).
- Execution Ledger: simulated fills in local DuckDB. Not a real broker.

If asked to change the product, suggest the user describe the change; you only explain.
"""


class DeskChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class DeskChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: List[DeskChatTurn] = Field(default_factory=list)
    context: Optional[Dict[str, Any]] = None


class DeskChatResponse(BaseModel):
    reply: str


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.2,
        api_key=settings.OPENAI_API_KEY or None,
    )


def answer_desk_question(req: DeskChatRequest) -> str:
    trimmed = req.history[-6:]
    transcript = "\n".join(f"{turn.role}: {turn.content}" for turn in trimmed)
    payload = {
        "question": req.message.strip(),
        "recent_chat": transcript,
        "live_context": req.context or {},
    }
    response = _get_llm().invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(payload, default=str)[:12000]),
        ]
    )
    content = getattr(response, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts = [str(item.get("text", item)) for item in content if item]
        return "\n".join(parts).strip()
    return "I could not generate a reply. Try asking about a specific panel, like RSI or Scout."
