import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from backend.app.config import settings
from backend.app.portfolio.portfolio_store import (
    AccountType,
    get_portfolio_user,
    replace_holdings,
    save_portfolio_user,
    update_account_snaptrade_balances,
    upsert_account,
)

logger = logging.getLogger(__name__)

# Set when SnapTrade rejects registerUser with code 1012 (personal keys).
_detected_personal_keys = False


def snaptrade_configured() -> bool:
    return bool(settings.SNAPTRADE_CLIENT_ID and settings.SNAPTRADE_CONSUMER_KEY)


def auth_mode() -> str:
    if _detected_personal_keys:
        return "personal"
    return (settings.SNAPTRADE_AUTH_MODE or "personal").strip().lower()


def is_personal_auth() -> bool:
    return auth_mode() == "personal"


def _is_personal_key_error(exc: Exception) -> bool:
    text = str(exc)
    return (
        "1012" in text
        or "Personal SnapTrade keys" in text
        or "registerUser is not available" in text
    )


def _response_body(response: Any) -> Any:
    if hasattr(response, "body"):
        return response.body
    return response


def _field(obj: Any, *names: str) -> Any:
    if obj is None:
        return None
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return None


def _parse_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _client(*, force_personal: bool = False):
    if not snaptrade_configured():
        raise RuntimeError("SnapTrade is not configured. Set SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY.")
    from snaptrade_client import SnapTrade
    from snaptrade_client.auth import SnapTradeAuth

    personal = force_personal or is_personal_auth()
    if personal:
        auth = SnapTradeAuth.personal_api_key(
            consumer_key=settings.SNAPTRADE_CONSUMER_KEY,
            client_id=settings.SNAPTRADE_CLIENT_ID,
        )
    else:
        auth = SnapTradeAuth.commercial_api_key(
            consumer_key=settings.SNAPTRADE_CONSUMER_KEY,
            client_id=settings.SNAPTRADE_CLIENT_ID,
        )
    return SnapTrade(auth=auth)


def _user_credentials(*, force_personal: bool = False) -> Tuple[Optional[str], Optional[str]]:
    if force_personal or is_personal_auth():
        return None, None
    return ensure_snaptrade_user(force_personal=force_personal)


def _infer_account_type(name: str) -> AccountType:
    lowered = name.lower()
    if "roth" in lowered:
        return "roth_ira"
    if "traditional" in lowered or ("ira" in lowered and "roth" not in lowered):
        return "traditional_ira"
    if "crypto" in lowered:
        return "other"
    if "individual" in lowered or "brokerage" in lowered or "investment" in lowered:
        return "taxable"
    return "other"


def ensure_snaptrade_user(*, force_personal: bool = False) -> Tuple[str, str]:
    if force_personal or is_personal_auth():
        raise RuntimeError("Personal SnapTrade keys do not use registerUser.")

    existing = get_portfolio_user()
    if existing:
        return str(existing["id"]), str(existing["user_secret"])

    client = _client(force_personal=False)
    user_id = f"mic-{uuid.uuid4().hex[:20]}"
    from snaptrade_client.model.snap_trade_register_user_request_body import SnapTradeRegisterUserRequestBody

    try:
        response = client.authentication.register_snap_trade_user(
            body=SnapTradeRegisterUserRequestBody(userId=user_id)
        )
    except Exception as exc:
        if _is_personal_key_error(exc):
            global _detected_personal_keys
            _detected_personal_keys = True
            logger.info("SnapTrade keys are personal; skipping registerUser.")
            raise
        raise

    body = _response_body(response)
    user_secret = _field(body, "userSecret", "user_secret")
    if not user_secret:
        raise RuntimeError("SnapTrade registration did not return a user secret.")
    save_portfolio_user(user_id, str(user_secret))
    return user_id, str(user_secret)


def _portal_login(*, redirect_url: Optional[str], force_personal: bool) -> Dict[str, str]:
    user_id, user_secret = _user_credentials(force_personal=force_personal)
    client = _client(force_personal=force_personal)
    kwargs: Dict[str, Any] = {
        "connection_type": "read",
        "connection_portal_version": "v4",
        "broker": "ROBINHOOD",
    }
    if user_id and user_secret:
        kwargs["user_id"] = user_id
        kwargs["user_secret"] = user_secret
    if redirect_url:
        kwargs["custom_redirect"] = redirect_url
        kwargs["immediate_redirect"] = True
    response = client.authentication.login_snap_trade_user(**kwargs)
    body = _response_body(response)
    redirect_uri = _field(body, "redirectURI", "redirectUri", "loginLink")
    if not redirect_uri:
        raise RuntimeError("SnapTrade did not return a connection portal URL.")
    return {
        "portal_url": str(redirect_uri),
        "user_id": user_id or "personal",
    }


def create_connection_portal_url(*, redirect_url: Optional[str] = None) -> Dict[str, str]:
    if is_personal_auth():
        return _portal_login(redirect_url=redirect_url, force_personal=True)

    try:
        return _portal_login(redirect_url=redirect_url, force_personal=False)
    except Exception as exc:
        if not _is_personal_key_error(exc):
            raise
        global _detected_personal_keys
        _detected_personal_keys = True
        logger.info("Retrying Robinhood connect using personal SnapTrade key flow.")
        return _portal_login(redirect_url=redirect_url, force_personal=True)


def _as_dict(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "model_dump"):
        return row.model_dump()
    if hasattr(row, "to_dict"):
        return row.to_dict()
    return {key: getattr(row, key) for key in dir(row) if not key.startswith("_")}


def _normalize_list_body(body: Any, *keys: str) -> List[Dict[str, Any]]:
    if isinstance(body, list):
        return [_as_dict(item) for item in body]
    payload = _as_dict(body) if body is not None and not isinstance(body, dict) else (body or {})
    for key in keys:
        nested = payload.get(key)
        if isinstance(nested, list):
            return [_as_dict(item) for item in nested]
    return []


def _symbol_from_position(position: Dict[str, Any]) -> Optional[str]:
    instrument = position.get("instrument")
    if isinstance(instrument, dict):
        raw = instrument.get("symbol") or instrument.get("raw_symbol") or instrument.get("ticker")
        if raw:
            cleaned = re.sub(r"[^A-Z0-9.^-]", "", str(raw).upper())
            return cleaned or None

    symbol_obj = position.get("symbol")
    if isinstance(symbol_obj, dict):
        raw = symbol_obj.get("symbol") or symbol_obj.get("raw_symbol") or symbol_obj.get("ticker")
    else:
        raw = _field(symbol_obj, "symbol", "raw_symbol", "ticker") or symbol_obj
    if not raw:
        return None
    cleaned = re.sub(r"[^A-Z0-9.^-]", "", str(raw).upper())
    return cleaned or None


def _position_to_holding(position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = _symbol_from_position(position)
    if not symbol:
        return None

    units = _parse_float(position.get("units") or position.get("quantity") or position.get("fractional_units"))
    if units <= 0:
        return None

    price = _parse_float(position.get("price") or position.get("current_price"))
    cost_basis = _parse_float(position.get("cost_basis"))
    avg_cost = _parse_float(
        position.get("average_purchase_price")
        or position.get("average_cost")
        or (cost_basis / units if cost_basis > 0 and units > 0 else price)
    )
    market_value = _parse_float(position.get("market_value") or (units * price))
    open_pnl = _parse_float(position.get("open_pnl") or ((price - avg_cost) * units))

    return {
        "symbol": symbol,
        "quantity": units,
        "average_cost": avg_cost,
        "current_price": price,
        "market_value": market_value,
        "unrealized_pnl": open_pnl,
    }


def _fetch_account_balances(client: Any, account_id: str, account_kwargs: Dict[str, Any]) -> Tuple[float, float]:
    try:
        balances_response = client.account_information.get_user_account_balance(
            account_id=account_id,
            **account_kwargs,
        )
        balances_body = _response_body(balances_response)
        balances = _normalize_list_body(balances_body, "balances")
        cash_total = 0.0
        buying_power = 0.0
        for raw_balance in balances:
            balance = _as_dict(raw_balance)
            cash_total += _parse_float(balance.get("cash"))
            buying_power += _parse_float(balance.get("buying_power"))
        if buying_power <= 0:
            buying_power = cash_total
        return round(cash_total, 2), round(buying_power, 2)
    except Exception as exc:
        logger.warning("SnapTrade balance fetch failed for account %s: %s", account_id, exc)
        return 0.0, 0.0


def sync_robinhood_holdings() -> Dict[str, Any]:
    force_personal = is_personal_auth()
    user_id, user_secret = _user_credentials(force_personal=force_personal)
    client = _client(force_personal=force_personal)
    account_kwargs: Dict[str, Any] = {}
    if user_id and user_secret:
        account_kwargs["user_id"] = user_id
        account_kwargs["user_secret"] = user_secret

    accounts_response = client.account_information.list_user_accounts(**account_kwargs)
    accounts_body = _response_body(accounts_response)
    accounts_list = _normalize_list_body(accounts_body, "accounts")

    synced_accounts = 0
    synced_positions = 0
    for raw_account in accounts_list:
        account = _as_dict(raw_account)
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

        position_kwargs = {"account_id": account_id, **account_kwargs}
        try:
            positions_response = client.account_information.get_all_account_positions(**position_kwargs)
            positions_body = _response_body(positions_response)
            positions_list = _normalize_list_body(positions_body, "results", "positions")
        except Exception as exc:
            logger.warning("SnapTrade positions fetch failed for account %s: %s", account_id, exc)
            positions_list = []

        holdings: List[Dict[str, Any]] = []
        for raw_position in positions_list:
            holding = _position_to_holding(_as_dict(raw_position))
            if holding:
                holdings.append(holding)

        replace_holdings(account_id, holdings)
        positions_value = round(sum(float(row.get("market_value") or 0) for row in holdings), 2)
        cash_balance, buying_power = _fetch_account_balances(client, account_id, account_kwargs)
        update_account_snaptrade_balances(
            account_id,
            cash_balance=cash_balance,
            buying_power=buying_power,
            positions_value=positions_value,
        )

        synced_accounts += 1
        synced_positions += len(holdings)
        logger.info(
            "Synced account %s (%s): %s positions, cash=%s, positions_value=%s",
            name,
            account_id,
            len(holdings),
            cash_balance,
            positions_value,
        )

    return {
        "status": "synced",
        "accounts": synced_accounts,
        "positions": synced_positions,
    }
