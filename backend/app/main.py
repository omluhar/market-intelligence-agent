from pathlib import Path
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.app.agents.desk_guide import DeskChatRequest, DeskChatResponse, answer_desk_question
from backend.app.collectors.news_collector import fetch_macro_headlines
from backend.app.execution.sandbox_router import (
    add_to_watchlist,
    get_order_history,
    get_recommendations,
    get_watchlist,
    remove_from_watchlist,
)
from backend.app.portfolio import portfolio_store
from backend.app.services.council_service import evaluate_symbol
from backend.app.services.market_cache import cached_history_bundle, load_overview
from backend.app.agents.portfolio_chat import PortfolioChatRequest, PortfolioChatResponse
from backend.app.services.portfolio_service import (
    portfolio_chat,
    portfolio_status,
    run_portfolio_analysis,
    start_broker_connection,
    sync_broker_holdings,
)
from backend.app.storage.agent_memory import agent_memory_stats
from backend.app.services.agent_control import AgentsPausedError, agents_status, assert_agents_active, set_agents_paused
from backend.app.services.scheduler_service import run_market_sweep, scheduler_running, shutdown_scheduler, start_scheduler
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


class HistoryBar(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class ScanResponse(BaseModel):
    ticker: str
    snapshot: Dict[str, Any]
    technical: Dict[str, Any]
    news: List[Dict[str, Any]]
    history: List[HistoryBar] = []
    proposal: Any = None
    tactical: Any = None
    risk: Any = None
    tactical_risk: Any = None
    order: Any = None
    tactical_order: Any = None
    dry_run: bool
    view_only: bool = False
    message: str


class WatchlistRequest(BaseModel):
    symbol: str


class SweepResponse(BaseModel):
    status: Literal["sweep triggered", "sweep already running", "agents paused"]


class AgentsStatusResponse(BaseModel):
    paused: bool
    scheduler_running: bool


class AgentsPauseRequest(BaseModel):
    paused: bool


class PortfolioConnectResponse(BaseModel):
    portal_url: str
    user_id: str


class AccountTypeUpdate(BaseModel):
    account_type: Literal["roth_ira", "taxable", "traditional_ira", "other"]


class ManualHoldingRequest(BaseModel):
    account_name: str
    account_type: Literal["roth_ira", "taxable", "traditional_ira", "other"]
    symbol: str
    quantity: float
    average_cost: float
    current_price: float


INTERVAL_PERIODS = {
    "5m": "5d",
    "15m": "60d",
    "60m": "3mo",
    "1h": "3mo",
    "1d": "1y",
    "1wk": "5y",
    "1mo": "max",
}


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
def fetch_history(
    ticker: str,
    interval: str = Query("1d"),
    period: Optional[str] = Query(None),
):
    symbol = ticker.upper().strip()
    candle = interval.strip().lower()
    if candle not in INTERVAL_PERIODS:
        raise HTTPException(status_code=400, detail=f"Unsupported interval: {interval}")
    lookback = (period or INTERVAL_PERIODS[candle]).strip()
    try:
        return cached_history_bundle(symbol, interval=candle, period=lookback)["history"]
    except Exception as exc:
        logger.exception("History fetch failed for %s", symbol)
        raise HTTPException(status_code=502, detail=f"History fetch failed for {symbol}: {exc}")


@app.get("/api/v1/overview/{ticker}", response_model=ScanResponse)
def ticker_overview(ticker: str):
    symbol = ticker.upper().strip()
    try:
        return ScanResponse.model_validate(load_overview(symbol))
    except Exception as exc:
        logger.exception("Overview failed for %s", symbol)
        raise HTTPException(status_code=502, detail=f"Overview failed for {symbol}: {exc}")


@app.get("/api/v1/agents/status", response_model=AgentsStatusResponse)
def fetch_agents_status():
    return AgentsStatusResponse(**agents_status(scheduler_running=scheduler_running()))


@app.post("/api/v1/agents/pause", response_model=AgentsStatusResponse)
def pause_agents(req: AgentsPauseRequest):
    set_agents_paused(req.paused)
    return AgentsStatusResponse(**agents_status(scheduler_running=scheduler_running()))


@app.post("/api/v1/scan/{ticker}", response_model=ScanResponse)
def scan_ticker(ticker: str):
    symbol = ticker.upper().strip()
    try:
        assert_agents_active()
        result = evaluate_symbol(
            symbol,
            include_news=True,
            persist=True,
            execute=True,
            source="SCAN",
        )
    except AgentsPausedError as exc:
        raise HTTPException(status_code=423, detail=str(exc))
    except Exception as exc:
        logger.exception("Council scan failed for %s", symbol)
        raise HTTPException(status_code=502, detail=f"Scan failed for {symbol}: {exc}")
    return ScanResponse.model_validate(result)


@app.post("/api/v1/sweep", response_model=SweepResponse)
def trigger_sweep():
    if agents_status(scheduler_running=scheduler_running())["paused"]:
        return SweepResponse(status="agents paused")
    started = run_market_sweep(background=True)
    if not started:
        return SweepResponse(status="sweep already running")
    return SweepResponse(status="sweep triggered")


@app.post("/api/v1/desk-chat", response_model=DeskChatResponse)
def desk_chat(req: DeskChatRequest):
    try:
        assert_agents_active()
        return DeskChatResponse(reply=answer_desk_question(req))
    except AgentsPausedError as exc:
        raise HTTPException(status_code=423, detail=str(exc))
    except Exception as exc:
        logger.exception("Desk guide failed")
        raise HTTPException(status_code=502, detail=f"Desk guide failed: {exc}")


@app.get("/api/v1/orders")
def fetch_orders() -> List[Dict[str, Any]]:
    return get_order_history()


@app.get("/api/v1/agent-memory/stats")
def fetch_agent_memory_stats():
    try:
        return agent_memory_stats()
    except Exception as exc:
        logger.exception("Agent memory stats failed")
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/v1/portfolio")
def fetch_portfolio():
    try:
        return portfolio_status()
    except Exception as exc:
        logger.exception("Portfolio fetch failed")
        raise HTTPException(status_code=502, detail=f"Portfolio fetch failed: {exc}")


@app.post("/api/v1/portfolio/connect", response_model=PortfolioConnectResponse)
def connect_broker():
    try:
        redirect = settings.PORTFOLIO_REDIRECT_URL.strip() or None
        payload = start_broker_connection(redirect_url=redirect)
        return PortfolioConnectResponse(**payload)
    except Exception as exc:
        logger.exception("Broker connect failed")
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/v1/portfolio/sync")
def sync_portfolio():
    try:
        return sync_broker_holdings()
    except Exception as exc:
        logger.exception("Portfolio sync failed")
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/v1/portfolio/analyze")
def analyze_portfolio():
    try:
        assert_agents_active()
        return run_portfolio_analysis()
    except AgentsPausedError as exc:
        raise HTTPException(status_code=423, detail=str(exc))
    except Exception as exc:
        logger.exception("Portfolio analyze failed")
        raise HTTPException(status_code=502, detail=f"Portfolio analysis failed: {exc}")


@app.post("/api/v1/portfolio/chat", response_model=PortfolioChatResponse)
def portfolio_advisor_chat(req: PortfolioChatRequest):
    try:
        assert_agents_active()
        return PortfolioChatResponse(reply=portfolio_chat(req))
    except AgentsPausedError as exc:
        raise HTTPException(status_code=423, detail=str(exc))
    except Exception as exc:
        logger.exception("Portfolio chat failed")
        raise HTTPException(status_code=502, detail=f"Portfolio chat failed: {exc}")


@app.patch("/api/v1/portfolio/accounts/{account_id}")
def update_account_type(account_id: str, req: AccountTypeUpdate):
    updated = portfolio_store.set_account_type(account_id, req.account_type)
    if not updated:
        raise HTTPException(status_code=404, detail="Account not found")
    return updated


@app.post("/api/v1/portfolio/manual-holding")
def add_manual_holding(req: ManualHoldingRequest):
    account = portfolio_store.ensure_manual_account(req.account_name, req.account_type)
    holding = portfolio_store.add_manual_holding(
        account_id=str(account["id"]),
        symbol=req.symbol,
        quantity=req.quantity,
        average_cost=req.average_cost,
        current_price=req.current_price,
    )
    return {"account": account, "holding": holding}


def _frontend_dir() -> Path:
    if settings.FRONTEND_DIST:
        return Path(settings.FRONTEND_DIST)
    return Path(__file__).resolve().parents[2] / "frontend" / "out"


_frontend = _frontend_dir()
if _frontend.is_dir() and (_frontend / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")
