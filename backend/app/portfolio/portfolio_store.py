import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import duckdb

from backend.app.config import settings

AccountType = Literal["roth_ira", "taxable", "traditional_ira", "other"]

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False


def _db_path() -> Path:
    path = (
        Path(settings.DUCKDB_PATH)
        if settings.DUCKDB_PATH
        else Path(__file__).resolve().parents[2] / "data" / "orders.db"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _jsonify(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _rows_to_dicts(cursor) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cursor.description]
    return [{col: _jsonify(val) for col, val in zip(cols, row)} for row in cursor.fetchall()]


def _get_conn():
    global _SCHEMA_READY
    conn = duckdb.connect(str(_db_path()))
    if _SCHEMA_READY:
        return conn
    with _SCHEMA_LOCK:
        if not _SCHEMA_READY:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_users (
                    id VARCHAR PRIMARY KEY,
                    user_secret VARCHAR NOT NULL,
                    created_at TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS portfolio_accounts (
                    id VARCHAR PRIMARY KEY,
                    external_id VARCHAR,
                    name VARCHAR,
                    account_type VARCHAR DEFAULT 'other',
                    brokerage VARCHAR,
                    source VARCHAR DEFAULT 'snaptrade',
                    last_synced_at TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS portfolio_holdings (
                    id VARCHAR PRIMARY KEY,
                    account_id VARCHAR,
                    symbol VARCHAR,
                    quantity DOUBLE,
                    average_cost DOUBLE,
                    current_price DOUBLE,
                    market_value DOUBLE,
                    unrealized_pnl DOUBLE,
                    updated_at TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS portfolio_insights (
                    id VARCHAR PRIMARY KEY,
                    account_id VARCHAR,
                    account_type VARCHAR,
                    symbol VARCHAR,
                    priority VARCHAR,
                    action VARCHAR,
                    title VARCHAR,
                    body VARCHAR,
                    generated_at TIMESTAMP
                );
            """)
            _SCHEMA_READY = True
    return conn


def get_portfolio_user() -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    rows = _rows_to_dicts(conn.execute("SELECT * FROM portfolio_users ORDER BY created_at DESC LIMIT 1"))
    return rows[0] if rows else None


def save_portfolio_user(user_id: str, user_secret: str) -> Dict[str, Any]:
    conn = _get_conn()
    now = _utcnow()
    conn.execute(
        """
        INSERT INTO portfolio_users (id, user_secret, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET user_secret = excluded.user_secret
        """,
        (user_id, user_secret, now),
    )
    return {"id": user_id, "created_at": now.isoformat()}


def upsert_account(
    *,
    account_id: str,
    external_id: Optional[str],
    name: str,
    account_type: AccountType,
    brokerage: str,
    source: str = "snaptrade",
) -> Dict[str, Any]:
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO portfolio_accounts (id, external_id, name, account_type, brokerage, source, last_synced_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT (id) DO UPDATE SET
            external_id = excluded.external_id,
            name = excluded.name,
            brokerage = excluded.brokerage,
            source = excluded.source
        """,
        (account_id, external_id, name, account_type, brokerage, source),
    )
    rows = _rows_to_dicts(conn.execute("SELECT * FROM portfolio_accounts WHERE id = ?", (account_id,)))
    return rows[0]


def set_account_type(account_id: str, account_type: AccountType) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    conn.execute(
        "UPDATE portfolio_accounts SET account_type = ? WHERE id = ?",
        (account_type, account_id),
    )
    rows = _rows_to_dicts(conn.execute("SELECT * FROM portfolio_accounts WHERE id = ?", (account_id,)))
    return rows[0] if rows else None


def replace_holdings(account_id: str, holdings: List[Dict[str, Any]]) -> None:
    conn = _get_conn()
    now = _utcnow()
    conn.execute("DELETE FROM portfolio_holdings WHERE account_id = ?", (account_id,))
    for row in holdings:
        conn.execute(
            """
            INSERT INTO portfolio_holdings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("id") or str(uuid.uuid4())[:12],
                account_id,
                str(row["symbol"]).upper(),
                float(row.get("quantity") or 0),
                float(row.get("average_cost") or 0),
                float(row.get("current_price") or 0),
                float(row.get("market_value") or 0),
                float(row.get("unrealized_pnl") or 0),
                now,
            ),
        )
    conn.execute(
        "UPDATE portfolio_accounts SET last_synced_at = ? WHERE id = ?",
        (now, account_id),
    )


def add_manual_holding(
    account_id: str,
    symbol: str,
    quantity: float,
    average_cost: float,
    current_price: float,
) -> Dict[str, Any]:
    market_value = round(quantity * current_price, 2)
    unrealized = round((current_price - average_cost) * quantity, 2)
    row = {
        "id": str(uuid.uuid4())[:12],
        "account_id": account_id,
        "symbol": symbol.upper(),
        "quantity": quantity,
        "average_cost": average_cost,
        "current_price": current_price,
        "market_value": market_value,
        "unrealized_pnl": unrealized,
    }
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO portfolio_holdings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["id"],
            account_id,
            row["symbol"],
            quantity,
            average_cost,
            current_price,
            market_value,
            unrealized,
            _utcnow(),
        ),
    )
    return row


def ensure_manual_account(name: str, account_type: AccountType) -> Dict[str, Any]:
    conn = _get_conn()
    rows = _rows_to_dicts(
        conn.execute(
            "SELECT * FROM portfolio_accounts WHERE source = 'manual' AND name = ? LIMIT 1",
            (name,),
        )
    )
    if rows:
        return rows[0]
    account_id = str(uuid.uuid4())[:12]
    return upsert_account(
        account_id=account_id,
        external_id=None,
        name=name,
        account_type=account_type,
        brokerage="manual",
        source="manual",
    )


def save_insights(insights: List[Dict[str, Any]]) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM portfolio_insights")
    now = _utcnow()
    for insight in insights:
        conn.execute(
            """
            INSERT INTO portfolio_insights VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                insight.get("id") or str(uuid.uuid4())[:12],
                insight.get("account_id"),
                insight.get("account_type"),
                insight.get("symbol"),
                insight.get("priority", "medium"),
                insight.get("action", "REVIEW"),
                insight.get("title"),
                insight.get("body"),
                now,
            ),
        )


def holding_context_for_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    ticker = symbol.upper().strip()
    rows = _rows_to_dicts(
        conn.execute(
            """
            SELECT h.*, a.account_type, a.name AS account_name
            FROM portfolio_holdings h
            JOIN portfolio_accounts a ON a.id = h.account_id
            WHERE h.symbol = ?
            """,
            (ticker,),
        )
    )
    if not rows:
        return None
    total = float(
        conn.execute("SELECT COALESCE(SUM(market_value), 0) FROM portfolio_holdings").fetchone()[0]
    )
    combined_value = sum(float(row.get("market_value") or 0) for row in rows)
    return {
        "owned": True,
        "quantity": round(sum(float(row.get("quantity") or 0) for row in rows), 4),
        "market_value": round(combined_value, 2),
        "weight_pct": round((combined_value / total) * 100, 2) if total > 0 else 0,
        "accounts": [
            {
                "account_type": row.get("account_type"),
                "account_name": row.get("account_name"),
                "quantity": row.get("quantity"),
                "market_value": row.get("market_value"),
            }
            for row in rows
        ],
    }


def get_portfolio_dashboard() -> Dict[str, Any]:
    conn = _get_conn()
    user = get_portfolio_user()
    accounts = _rows_to_dicts(conn.execute("SELECT * FROM portfolio_accounts ORDER BY name"))
    holdings = _rows_to_dicts(
        conn.execute(
            """
            SELECT h.*, a.name AS account_name, a.account_type, a.brokerage
            FROM portfolio_holdings h
            JOIN portfolio_accounts a ON a.id = h.account_id
            ORDER BY h.market_value DESC
            """
        )
    )
    insights = _rows_to_dicts(
        conn.execute("SELECT * FROM portfolio_insights ORDER BY generated_at DESC")
    )
    total_value = round(sum(float(h.get("market_value") or 0) for h in holdings), 2)
    by_type: Dict[str, float] = {}
    for holding in holdings:
        acct_type = str(holding.get("account_type") or "other")
        by_type[acct_type] = by_type.get(acct_type, 0.0) + float(holding.get("market_value") or 0)
    return {
        "connected": user is not None,
        "user": user,
        "accounts": accounts,
        "holdings": holdings,
        "insights": insights,
        "total_value": total_value,
        "value_by_account_type": {k: round(v, 2) for k, v in by_type.items()},
    }
