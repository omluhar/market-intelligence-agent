import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.app.config import settings
from backend.app.portfolio.portfolio_store import AccountType, get_portfolio_user, replace_holdings, save_portfolio_user, upsert_account

logger = logging.getLogger(__name__)


def snaptrade_configured() -> bool:
    return bool(settings.SNAPTRADE_CLIENT_ID and settings.SNAPTRADE_CONSUMER_KEY)


def _client():
    if not snaptrade_configured():
        raise RuntimeError("SnapTrade is not configured. Set SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY.")
    from snaptrade_client import SnapTrade

    return SnapTrade(
        client_id=settings.SNAPTRADE_CLIENT_ID,
        consumer_key=settings.SNAPTRADE_CONSUMER_KEY,
    )


def _infer_account_type(name: str) -> AccountType:
    lowered = name.lower()
    if "roth" in lowered:
        return "roth_ira"
    if "traditional" in lowered or "ira" in lowered:
        return "traditional_ira"
    if "individual" in lowered or "brokerage" in lowered or "investment" in lowered:
        return "taxable"
    return "other"


def ensure_snaptrade_user() -> Tuple[str, str]:
    existing = get_portfolio_user()
    if existing:
        return str(existing["id"]), str(existing["user_secret"])

    client = _client()
    response = client.authentication.register_snap_trade_user(body={})
    body = response.body if hasattr(response, "body") else response
    user_id = str(body["userId"])
    user_secret = str(body["userSecret"])
    save_portfolio_user(user_id, user_secret)
    return user_id, user_secret


def create_connection_portal_url(*, redirect_url: Optional[str] = None) -> Dict[str, str]:
    user_id, user_secret = ensure_snaptrade_user()
    client = _client()
    kwargs: Dict[str, Any] = {
        "user_id": user_id,
        "user_secret": user_secret,
        "connection_type": "read",
        "connection_portal_version": "v4",
    }
    if redirect_url:
        kwargs["custom_redirect"] = redirect_url
        kwargs["immediate_redirect"] = True
    response = client.authentication.login_snap_trade_user(**kwargs)
    body = response.body if hasattr(response, "body") else response
    redirect_uri = body.get("redirectURI") or body.get("redirectUri") or body.get("loginLink")
    if not redirect_uri:
        raise RuntimeError("SnapTrade did not return a connection portal URL.")
    return {"portal_url": str(redirect_uri), "user_id": user_id}


def _symbol_from_position(position: Dict[str, Any]) -> Optional[str]:
    symbol_obj = position.get("symbol") or {}
    if isinstance(symbol_obj, dict):
        raw = symbol_obj.get("symbol") or symbol_obj.get("raw_symbol") or symbol_obj.get("ticker")
    else:
        raw = symbol_obj
    if not raw:
        return None
    cleaned = re.sub(r"[^A-Z0-9.^-]", "", str(raw).upper())
    return cleaned or None


def sync_robinhood_holdings() -> Dict[str, Any]:
    user_id, user_secret = ensure_snaptrade_user()
    client = _client()
    accounts_response = client.account_information.list_user_accounts(
        user_id=user_id,
        user_secret=user_secret,
    )
    accounts_body = accounts_response.body if hasattr(accounts_response, "body") else accounts_response
    if not isinstance(accounts_body, list):
        accounts_body = accounts_body.get("accounts") or []

    synced_accounts = 0
    synced_positions = 0
    for account in accounts_body:
        account_id = str(account.get("id") or account.get("account_id") or "")
        if not account_id:
            continue
        name = str(account.get("name") or account.get("number") or "Brokerage account")
        brokerage = str((account.get("institution_name") or account.get("brokerage") or "robinhood")).lower()
        acct_type = _infer_account_type(name)
        upsert_account(
            account_id=account_id,
            external_id=account_id,
            name=name,
            account_type=acct_type,
            brokerage=brokerage,
            source="snaptrade",
        )
        positions_response = client.account_information.get_user_account_positions(
            account_id=account_id,
            user_id=user_id,
            user_secret=user_secret,
        )
        positions_body = positions_response.body if hasattr(positions_response, "body") else positions_response
        if not isinstance(positions_body, list):
            positions_body = positions_body.get("positions") or []

        holdings: List[Dict[str, Any]] = []
        for position in positions_body:
            symbol = _symbol_from_position(position)
            if not symbol:
                continue
            units = float(position.get("units") or position.get("quantity") or 0)
            if units <= 0:
                continue
            price = float(position.get("price") or position.get("current_price") or 0)
            avg_cost = float(position.get("average_purchase_price") or position.get("average_cost") or price)
            market_value = float(position.get("market_value") or (units * price))
            open_pnl = float(position.get("open_pnl") or ((price - avg_cost) * units))
            holdings.append(
                {
                    "symbol": symbol,
                    "quantity": units,
                    "average_cost": avg_cost,
                    "current_price": price,
                    "market_value": market_value,
                    "unrealized_pnl": open_pnl,
                }
            )
        replace_holdings(account_id, holdings)
        synced_accounts += 1
        synced_positions += len(holdings)

    return {
        "status": "synced",
        "accounts": synced_accounts,
        "positions": synced_positions,
    }
