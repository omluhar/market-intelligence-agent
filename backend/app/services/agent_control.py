from typing import Any, Dict

from backend.app.portfolio import portfolio_store


class AgentsPausedError(Exception):
    """Raised when LLM-heavy agent work is requested while paused."""


def agents_paused() -> bool:
    return portfolio_store.get_agents_paused()


def set_agents_paused(paused: bool) -> bool:
    return portfolio_store.set_agents_paused(paused)


def assert_agents_active() -> None:
    if agents_paused():
        raise AgentsPausedError(
            "Agents are paused. Turn them back on from the desk header to save credits."
        )


def agents_status(*, scheduler_running: bool) -> Dict[str, Any]:
    return {
        "paused": agents_paused(),
        "scheduler_running": scheduler_running,
    }
