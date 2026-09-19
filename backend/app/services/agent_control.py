import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.app.portfolio import portfolio_store

logger = logging.getLogger(__name__)

CATCH_UP_GAP_HOURS = 24


class AgentsPausedError(Exception):
    """Raised when LLM-heavy agent work is requested while paused."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def agents_paused() -> bool:
    return portfolio_store.get_agents_paused()


def get_last_sweep_at() -> Optional[datetime]:
    return _parse_iso(portfolio_store.get_agent_setting("last_sweep_at"))


def touch_last_sweep_at() -> None:
    portfolio_store.set_agent_setting("last_sweep_at", _utcnow().isoformat())


def set_agents_paused(paused: bool) -> Dict[str, Any]:
    portfolio_store.set_agents_paused(paused)
    now = _utcnow().isoformat()
    catch_up_started = False

    if paused:
        portfolio_store.set_agent_setting("paused_at", now)
    else:
        portfolio_store.set_agent_setting("last_resumed_at", now)
        catch_up_started = _start_catch_up_if_needed()

    status = agents_status(scheduler_running=False)
    status["catch_up_started"] = catch_up_started
    return status


def _start_catch_up_if_needed() -> bool:
    last_sweep = get_last_sweep_at()
    if last_sweep is None:
        logger.info("No prior sweep recorded; starting catch-up research.")
        return _trigger_catch_up_sweep()

    gap_hours = (_utcnow() - last_sweep).total_seconds() / 3600
    if gap_hours < CATCH_UP_GAP_HOURS:
        logger.info("Last sweep %.1f hours ago; skip catch-up.", gap_hours)
        return False

    logger.info("Last sweep %.1f hours ago; starting catch-up research.", gap_hours)
    return _trigger_catch_up_sweep()


def _trigger_catch_up_sweep() -> bool:
    from backend.app.services.scheduler_service import run_market_sweep

    portfolio_store.set_agent_setting("catch_up_requested_at", _utcnow().isoformat())
    started = run_market_sweep(background=True)
    if started:
        from backend.app.storage.agent_memory import log_agent_event

        log_agent_event(
            "catch_up_sweep",
            payload={"reason": "resume_after_idle", "last_sweep_at": portfolio_store.get_agent_setting("last_sweep_at")},
        )
    return started


def assert_agents_active() -> None:
    if agents_paused():
        raise AgentsPausedError(
            "Agents are paused. Turn them back on from the desk header to save credits."
        )


def agents_status(*, scheduler_running: bool) -> Dict[str, Any]:
    last_sweep = get_last_sweep_at()
    days_since_sweep = None
    if last_sweep:
        days_since_sweep = round((_utcnow() - last_sweep).total_seconds() / 86400, 2)

    return {
        "paused": agents_paused(),
        "scheduler_running": scheduler_running,
        "last_sweep_at": last_sweep.isoformat() if last_sweep else None,
        "last_paused_at": portfolio_store.get_agent_setting("paused_at"),
        "days_since_sweep": days_since_sweep,
    }
