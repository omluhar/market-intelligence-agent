import logging
from typing import Any, Dict, Optional

from backend.app.agents.portfolio_advisor import analyze_portfolio
from backend.app.agents.portfolio_chat import PortfolioChatRequest, answer_portfolio_question
from backend.app.portfolio import portfolio_store, snaptrade_service
from backend.app.storage.agent_memory import log_agent_event, save_portfolio_chat_message

logger = logging.getLogger(__name__)


def portfolio_status() -> Dict[str, Any]:
    dashboard = portfolio_store.get_portfolio_dashboard()
    dashboard["snaptrade_configured"] = snaptrade_service.snaptrade_configured()
    dashboard["snaptrade_auth_mode"] = snaptrade_service.auth_mode()
    if dashboard["snaptrade_configured"]:
        dashboard["broker_linked"] = bool(dashboard.get("accounts"))
    dashboard["analysis_summary"] = portfolio_store.get_portfolio_summary()
    return dashboard


def start_broker_connection(redirect_url: Optional[str] = None) -> Dict[str, str]:
    if not snaptrade_service.snaptrade_configured():
        raise RuntimeError(
            "SnapTrade credentials missing. Add SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY on the server."
        )
    return snaptrade_service.create_connection_portal_url(redirect_url=redirect_url)


def sync_broker_holdings() -> Dict[str, Any]:
    if not snaptrade_service.snaptrade_configured():
        raise RuntimeError("SnapTrade is not configured on this deployment.")
    return snaptrade_service.sync_robinhood_holdings()


def run_portfolio_analysis() -> Dict[str, Any]:
    dashboard = portfolio_store.get_portfolio_dashboard()
    result = analyze_portfolio(dashboard)
    if result.get("insights"):
        portfolio_store.save_insights(result["insights"])
    if result.get("summary"):
        portfolio_store.set_portfolio_summary(str(result["summary"]))
    log_agent_event(
        "portfolio_analysis",
        payload={
            "summary": result.get("summary"),
            "insight_count": len(result.get("insights") or []),
            "symbols": [h.get("symbol") for h in dashboard.get("holdings") or []],
        },
    )
    refreshed = portfolio_store.get_portfolio_dashboard()
    refreshed["analysis_summary"] = result.get("summary")
    refreshed["research"] = result.get("research")
    refreshed["snaptrade_configured"] = snaptrade_service.snaptrade_configured()
    return refreshed


def portfolio_chat(req: PortfolioChatRequest) -> str:
    dashboard = portfolio_store.get_portfolio_dashboard()
    dashboard["analysis_summary"] = portfolio_store.get_portfolio_summary()
    reply = answer_portfolio_question(req, dashboard)
    save_portfolio_chat_message("user", req.message.strip())
    save_portfolio_chat_message("assistant", reply)
    return reply
