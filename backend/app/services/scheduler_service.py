import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from backend.app.execution.sandbox_router import get_watchlist
from backend.app.services.council_service import evaluate_symbol

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()
_sweep_lock = threading.Lock()

DISCOVERY_UNIVERSE = ["GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "VZ", "DIS", "JNJ", "KO"]


def _run_market_sweep() -> None:
    logger.info("Executing autonomous market background sweep...")
    watchlist = get_watchlist()
    full_scan_targets = list(dict.fromkeys(watchlist + DISCOVERY_UNIVERSE))

    for symbol in full_scan_targets:
        try:
            evaluate_symbol(
                symbol,
                include_news=False,
                persist=True,
                execute=symbol in watchlist,
                source="WATCHLIST" if symbol in watchlist else "DISCOVERY_AGENT",
            )
        except Exception as exc:
            logger.warning("Background scan failed for %s: %s", symbol, exc)
    logger.info("Market sweep complete.")


def run_market_sweep(background: bool = False) -> bool:
    """Run a full-universe council sweep. Returns False if a sweep is already in flight."""
    if not _sweep_lock.acquire(blocking=False):
        logger.info("Skipping sweep; another sweep is already running.")
        return False

    def _job() -> None:
        try:
            _run_market_sweep()
        finally:
            _sweep_lock.release()

    if background:
        threading.Thread(target=_job, daemon=True, name="market-sweep").start()
        return True

    _job()
    return True


def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(
            lambda: run_market_sweep(background=True),
            "interval",
            minutes=10,
            id="market_sweep_job",
        )
        scheduler.start()
        logger.info("Background market scheduler initialized.")


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
