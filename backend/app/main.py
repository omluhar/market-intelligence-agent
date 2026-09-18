from pathlib import Path
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.app.collectors.news_collector import fetch_macro_headlines
from backend.app.collectors.technical_collector import fetch_ohlcv
from backend.app.execution.sandbox_router import (
    add_to_watchlist,
    get_order_history,
    get_recommendations,
    get_watchlist,
    remove_from_watchlist,
)
from backend.app.services.council_service import evaluate_symbol
from backend.app.services.scheduler_service import run_market_sweep, shutdown_scheduler, start_scheduler
from backend.app.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="Market Intelligence Engine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanResponse(BaseModel):
    ticker: str
    snapshot: Dict[str, Any]
    technical: Dict[str, Any]
    news: List[Dict[str, Any]]
    proposal: Any = None
    tactical: Any = None
    risk: Any = None
    tactical_risk: Any = None
    order: Any = None
    tactical_order: Any = None
    dry_run: bool
    message: str


class WatchlistRequest(BaseModel):
    symbol: str


class HistoryBar(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class SweepResponse(BaseModel):
    status: Literal["sweep triggered", "sweep already running"]


@app.get("/health")
def health_check():
    return {"status": "ok", "dry_run": settings.DRY_RUN}


@app.get("/api/v1/watchlist")
def fetch_watchlist():
    return get_watchlist()


@app.post("/api/v1/watchlist")
def add_ticker(req: WatchlistRequest):
    add_to_watchlist(req.symbol)
    return {"status": "success", "watchlist": get_watchlist()}


@app.delete("/api/v1/watchlist/{symbol}")
def delete_ticker(symbol: str):
    remove_from_watchlist(symbol)
    return {"status": "success", "watchlist": get_watchlist()}


@app.get("/api/v1/recommendations")
def fetch_recommendations():
    return get_recommendations()


@app.get("/api/v1/macro-news")
def fetch_macro():
    return fetch_macro_headlines()


@app.get("/api/v1/history/{ticker}", response_model=List[HistoryBar])
def fetch_history(ticker: str):
    symbol = ticker.upper().strip()
    try:
        return fetch_ohlcv(symbol)
    except Exception as exc:
        logger.exception("History fetch failed for %s", symbol)
        raise HTTPException(status_code=502, detail=f"History fetch failed for {symbol}: {exc}")


@app.post("/api/v1/scan/{ticker}", response_model=ScanResponse)
def scan_ticker(ticker: str):
    symbol = ticker.upper().strip()
    try:
        result = evaluate_symbol(
            symbol,
            include_news=True,
            persist=True,
            execute=True,
            source="SCAN",
        )
    except Exception as exc:
        logger.exception("Council scan failed for %s", symbol)
        raise HTTPException(status_code=502, detail=f"Scan failed for {symbol}: {exc}")
    return ScanResponse.model_validate(result)


@app.post("/api/v1/sweep", response_model=SweepResponse)
def trigger_sweep():
    started = run_market_sweep(background=True)
    if not started:
        return SweepResponse(status="sweep already running")
    return SweepResponse(status="sweep triggered")


@app.get("/api/v1/orders")
def fetch_orders() -> List[Dict[str, Any]]:
    return get_order_history()


def _frontend_dir() -> Path:
    if settings.FRONTEND_DIST:
        return Path(settings.FRONTEND_DIST)
    return Path(__file__).resolve().parents[2] / "frontend" / "out"


_frontend = _frontend_dir()
if _frontend.is_dir() and (_frontend / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")
