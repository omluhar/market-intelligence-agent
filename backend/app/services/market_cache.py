import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

from backend.app.collectors.news_collector import fetch_ticker_news
from backend.app.collectors.price_collector import fetch_market_snapshot
from backend.app.collectors.technical_collector import (
    fetch_history_df,
    ohlcv_from_df,
    technical_from_df,
)
from backend.app.execution.sandbox_router import get_recommendations_for_symbol

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

SNAPSHOT_TTL_SEC = 120.0
HISTORY_TTL_SEC = 600.0
NEWS_TTL_SEC = 600.0
OVERVIEW_TTL_SEC = 90.0
FETCH_TIMEOUT_SEC = 12.0

T = TypeVar("T")

_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="market-cache")
_LOCK = threading.Lock()
_STORE: Dict[str, Tuple[float, Any]] = {}
_INFLIGHT: Dict[str, Any] = {}


def _cache_get(key: str) -> Optional[Any]:
    with _LOCK:
        hit = _STORE.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    return None


def _cache_set(key: str, value: Any, ttl: float) -> Any:
    with _LOCK:
        _STORE[key] = (time.monotonic() + ttl, value)
    return value


def _coalesce(key: str, factory: Callable[[], T]) -> T:
    cached = _cache_get(key)
    if cached is not None:
        return cached
    with _LOCK:
        future = _INFLIGHT.get(key)
        if future is None:
            future = _POOL.submit(factory)
            _INFLIGHT[key] = future
    try:
        value = future.result(timeout=FETCH_TIMEOUT_SEC)
        return value
    finally:
        with _LOCK:
            if _INFLIGHT.get(key) is future:
                _INFLIGHT.pop(key, None)


def cached_snapshot(symbol: str) -> Dict[str, Any]:
    key = f"snapshot:{symbol}"

    def _load() -> Dict[str, Any]:
        payload = fetch_market_snapshot(symbol)
        return _cache_set(key, payload, SNAPSHOT_TTL_SEC)

    return _coalesce(key, _load)


def cached_history_bundle(symbol: str, interval: str = "1d", period: str = "1y") -> Dict[str, Any]:
    key = f"history:{symbol}:{interval}:{period}"

    def _load() -> Dict[str, Any]:
        hist = fetch_history_df(symbol, period=period, interval=interval)
        payload = {
            "technical": technical_from_df(hist) if interval in {"1d", "1wk", "1mo"} else None,
            "history": ohlcv_from_df(hist),
        }
        return _cache_set(key, payload, HISTORY_TTL_SEC)

    return _coalesce(key, _load)


def cached_news(symbol: str) -> List[Dict[str, Any]]:
    key = f"news:{symbol}"

    def _load() -> List[Dict[str, Any]]:
        try:
            payload = fetch_ticker_news(symbol)
        except Exception as exc:
            logger.warning("News fetch failed for %s: %s", symbol, exc)
            payload = []
        return _cache_set(key, payload, NEWS_TTL_SEC)

    try:
        return _coalesce(key, _load)
    except Exception as exc:
        logger.warning("News cache miss for %s: %s", symbol, exc)
        return []


def load_market_bundle(symbol: str, include_news: bool = True) -> Dict[str, Any]:
    ticker = symbol.upper().strip()
    snapshot_future = _POOL.submit(cached_snapshot, ticker)
    history_future = _POOL.submit(cached_history_bundle, ticker)
    news_future = _POOL.submit(cached_news, ticker) if include_news else None

    try:
        snapshot = snapshot_future.result(timeout=FETCH_TIMEOUT_SEC)
    except Exception as exc:
        logger.warning("Snapshot failed for %s: %s", ticker, exc)
        snapshot_future.cancel()
        raise

    try:
        history_bundle = history_future.result(timeout=FETCH_TIMEOUT_SEC)
        technical = history_bundle["technical"] or dict(EMPTY_TECHNICAL)
        history = history_bundle["history"]
    except Exception as exc:
        logger.warning("History failed for %s: %s", ticker, exc)
        technical = dict(EMPTY_TECHNICAL)
        history = []

    news: List[Dict[str, Any]] = []
    if news_future is not None:
        try:
            news = news_future.result(timeout=6)
        except Exception as exc:
            logger.warning("News timed out for %s: %s", ticker, exc)
            news = []

    return {
        "ticker": ticker,
        "snapshot": snapshot,
        "technical": technical,
        "history": history,
        "news": news,
    }


def _recs_to_agent_cards(symbol: str) -> Dict[str, Any]:
    recs = get_recommendations_for_symbol(symbol)
    proposal = None
    tactical = None
    long_rec = recs.get("LONG_TERM_VALUE")
    short_rec = recs.get("SHORT_TERM_MOMENTUM")
    if long_rec:
        proposal = {
            "symbol": long_rec["symbol"],
            "action": long_rec["action"],
            "target_price": long_rec["target_price"],
            "shares": 0,
            "total_value": 0,
            "thesis": long_rec.get("thesis") or "",
        }
    if short_rec:
        tactical = {
            "symbol": short_rec["symbol"],
            "action": short_rec["action"],
            "target_price": short_rec["target_price"],
            "stop_loss": None,
            "time_horizon": "SHORT_TERM",
            "setup_type": "MOMENTUM_BREAKOUT",
            "confidence": 0,
            "rationale": short_rec.get("thesis") or "",
        }
    return {"proposal": proposal, "tactical": tactical}


def load_overview(symbol: str) -> Dict[str, Any]:
    ticker = symbol.upper().strip()
    key = f"overview:{ticker}"
    cached = _cache_get(key)
    if cached is not None:
        cards = _recs_to_agent_cards(ticker)
        return {**cached, **cards}

    bundle = load_market_bundle(ticker, include_news=True)
    cards = _recs_to_agent_cards(ticker)
    payload = {
        "ticker": ticker,
        "snapshot": bundle["snapshot"],
        "technical": bundle["technical"],
        "news": bundle["news"],
        "history": bundle["history"],
        "proposal": cards["proposal"],
        "tactical": cards["tactical"],
        "risk": None,
        "tactical_risk": None,
        "order": None,
        "tactical_order": None,
        "dry_run": True,
        "view_only": True,
        "message": (
            "Quotes loaded. Click Scan to run the council."
            if not cards["proposal"] and not cards["tactical"]
            else "Quotes loaded. Showing last council thesis; click Scan to refresh agents."
        ),
    }
    _cache_set(key, {k: v for k, v in payload.items() if k not in ("proposal", "tactical")}, OVERVIEW_TTL_SEC)
    return payload
