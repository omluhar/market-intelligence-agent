from typing import Any, Optional, TypedDict

import yfinance as yf


class MarketSnapshot(TypedDict):
    symbol: str
    last_price: float
    market_cap: Any
    fifty_two_week_high: float
    fifty_two_week_low: float
    trailing_pe: Optional[float]
    forward_pe: Optional[float]
    debt_to_equity: Optional[float]
    free_cashflow: Optional[float]


def fetch_market_snapshot(ticker: str) -> MarketSnapshot:
    stock = yf.Ticker(ticker)
    fast_info = stock.fast_info
    info = stock.info

    return {
        "symbol": ticker.upper(),
        "last_price": float(getattr(fast_info, "last_price", 0.0) or 0.0),
        "market_cap": getattr(fast_info, "market_cap", 0),
        "fifty_two_week_high": float(getattr(fast_info, "year_high", 0.0) or 0.0),
        "fifty_two_week_low": float(getattr(fast_info, "year_low", 0.0) or 0.0),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "debt_to_equity": info.get("debtToEquity"),
        "free_cashflow": info.get("freeCashflow"),
    }
