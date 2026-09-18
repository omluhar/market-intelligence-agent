import math
from typing import Any, Dict, List, Literal, Optional, TypedDict

import pandas as pd
import yfinance as yf


class TechnicalSnapshot(TypedDict):
    sma_50: Optional[float]
    sma_200: Optional[float]
    rsi_14: Optional[float]
    volume_surge_ratio: Optional[float]
    trend: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    last_price: float
    drawdown_from_high_pct: Optional[float]
    golden_cross: Optional[bool]


class OhlcvBar(TypedDict):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def fetch_history_df(ticker: str, period: str = "1y") -> pd.DataFrame:
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period, auto_adjust=True)
    if hist is None or hist.empty:
        raise ValueError(f"No historical bars returned for {ticker}")
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)
    return hist


def _rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.mask(avg_loss == 0)
    rsi = 100 - (100 / (1 + rs))
    return rsi.where(avg_loss != 0, 100.0)


def technical_from_df(hist: pd.DataFrame) -> TechnicalSnapshot:
    close = hist["Close"].astype(float)
    high = hist["High"].astype(float)
    volume = hist["Volume"].astype(float)

    sma_50 = _finite(close.rolling(50).mean().iloc[-1])
    sma_200 = _finite(close.rolling(200).mean().iloc[-1])
    rsi_14 = _finite(_rsi_wilder(close, 14).iloc[-1])

    avg_20d_volume = _finite(volume.tail(20).mean())
    today_volume = _finite(volume.iloc[-1])
    volume_surge_ratio = None
    if today_volume is not None and avg_20d_volume and avg_20d_volume > 0:
        volume_surge_ratio = round(today_volume / avg_20d_volume, 4)

    last_price = _finite(close.iloc[-1]) or 0.0
    year_high = _finite(high.max())
    drawdown_from_high_pct = None
    if year_high and year_high > 0:
        drawdown_from_high_pct = round(((last_price - year_high) / year_high) * 100.0, 4)

    golden_cross: Optional[bool] = None
    if sma_50 is not None and sma_200 is not None:
        golden_cross = sma_50 > sma_200

    trend: Literal["BULLISH", "BEARISH", "NEUTRAL"] = "NEUTRAL"
    if sma_50 is not None and sma_200 is not None:
        if sma_50 > sma_200 and last_price > sma_50:
            trend = "BULLISH"
        elif sma_50 < sma_200 and last_price < sma_50:
            trend = "BEARISH"

    return {
        "sma_50": round(sma_50, 4) if sma_50 is not None else None,
        "sma_200": round(sma_200, 4) if sma_200 is not None else None,
        "rsi_14": round(rsi_14, 4) if rsi_14 is not None else None,
        "volume_surge_ratio": volume_surge_ratio,
        "trend": trend,
        "last_price": round(last_price, 4),
        "drawdown_from_high_pct": drawdown_from_high_pct,
        "golden_cross": golden_cross,
    }


def ohlcv_from_df(hist: pd.DataFrame) -> List[OhlcvBar]:
    index = pd.DatetimeIndex(hist.index)
    if index.tz is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    bars: List[OhlcvBar] = []
    opens = hist["Open"].to_numpy()
    highs = hist["High"].to_numpy()
    lows = hist["Low"].to_numpy()
    closes = hist["Close"].to_numpy()
    volumes = hist["Volume"].to_numpy()
    dates = index.strftime("%Y-%m-%d")
    for i in range(len(hist)):
        open_px = _finite(opens[i])
        high_px = _finite(highs[i])
        low_px = _finite(lows[i])
        close_px = _finite(closes[i])
        volume = _finite(volumes[i])
        if None in (open_px, high_px, low_px, close_px):
            continue
        bars.append(
            {
                "time": str(dates[i]),
                "open": round(open_px, 4),
                "high": round(high_px, 4),
                "low": round(low_px, 4),
                "close": round(close_px, 4),
                "volume": round(volume or 0.0, 2),
            }
        )
    return bars


def fetch_technical_snapshot(ticker: str) -> TechnicalSnapshot:
    return technical_from_df(fetch_history_df(ticker, period="1y"))


def fetch_ohlcv(ticker: str, period: str = "1y") -> List[Dict[str, Any]]:
    return ohlcv_from_df(fetch_history_df(ticker, period=period))
