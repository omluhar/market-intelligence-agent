import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import duckdb
from backend.app.agents.risk_guardian import RiskEvaluation, TradeProposal
from backend.app.config import settings

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False


def _db_path() -> Path:
    path = Path(settings.DUCKDB_PATH) if settings.DUCKDB_PATH else Path(__file__).resolve().parents[2] / "data" / "orders.db"
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
    return [
        {col: _jsonify(val) for col, val in zip(cols, row)}
        for row in cursor.fetchall()
    ]


def _get_conn():
    global _SCHEMA_READY
    conn = duckdb.connect(str(_db_path()))
    if _SCHEMA_READY:
        return conn
    with _SCHEMA_LOCK:
        if not _SCHEMA_READY:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id VARCHAR PRIMARY KEY,
                    timestamp TIMESTAMP,
                    symbol VARCHAR,
                    action VARCHAR,
                    shares INTEGER,
                    price DOUBLE,
                    total_value DOUBLE,
                    status VARCHAR,
                    is_dry_run BOOLEAN,
                    thesis VARCHAR,
                    reason VARCHAR
                );
                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol VARCHAR PRIMARY KEY,
                    added_at TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS recommendations (
                    symbol VARCHAR,
                    horizon VARCHAR,
                    action VARCHAR,
                    target_price DOUBLE,
                    trailing_pe DOUBLE,
                    forward_pe DOUBLE,
                    thesis VARCHAR,
                    source VARCHAR,
                    updated_at TIMESTAMP,
                    PRIMARY KEY (symbol, horizon)
                );
            """)
            _migrate_recommendations(conn)
            _SCHEMA_READY = True
    return conn


def _migrate_recommendations(conn) -> None:
    cols = [row[0] for row in conn.execute("DESCRIBE recommendations").fetchall()]
    if "horizon" in cols:
        return
    conn.execute("ALTER TABLE recommendations RENAME TO recommendations_legacy")
    conn.execute("""
        CREATE TABLE recommendations (
            symbol VARCHAR,
            horizon VARCHAR,
            action VARCHAR,
            target_price DOUBLE,
            trailing_pe DOUBLE,
            forward_pe DOUBLE,
            thesis VARCHAR,
            source VARCHAR,
            updated_at TIMESTAMP,
            PRIMARY KEY (symbol, horizon)
        );
    """)
    conn.execute("""
        INSERT INTO recommendations
        SELECT symbol, 'LONG_TERM_VALUE', action, target_price, trailing_pe, forward_pe, thesis, source, updated_at
        FROM recommendations_legacy
    """)
    conn.execute("DROP TABLE recommendations_legacy")


def execute_order(proposal: TradeProposal, risk: RiskEvaluation, is_dry_run: bool = True) -> Dict[str, Any]:
    order_id = str(uuid.uuid4())[:8]
    now = _utcnow()
    shares = risk.adjusted_shares
    price = proposal.target_price
    total_value = round(shares * price, 2)
    status = "SIMULATED_FILLED" if is_dry_run else "SUBMITTED"

    conn = _get_conn()
    conn.execute("""
        INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order_id, now, proposal.symbol, proposal.action,
        shares, price, total_value, status, is_dry_run,
        proposal.thesis, risk.reason
    ))
    conn.close()

    return {
        "order_id": order_id,
        "id": order_id,
        "timestamp": now.isoformat(),
        "symbol": proposal.symbol,
        "action": proposal.action,
        "shares": shares,
        "price": price,
        "total_value": total_value,
        "status": status,
        "is_dry_run": is_dry_run,
        "thesis": proposal.thesis,
        "reason": risk.reason
    }


def get_order_history() -> List[Dict[str, Any]]:
    conn = _get_conn()
    cursor = conn.execute("""
        SELECT id, timestamp, symbol, action, shares, price, total_value, status, is_dry_run, thesis, reason
        FROM orders
        ORDER BY timestamp DESC
    """)
    rows = _rows_to_dicts(cursor)
    conn.close()
    return rows


def add_to_watchlist(symbol: str):
    conn = _get_conn()
    conn.execute("INSERT OR REPLACE INTO watchlist VALUES (?, ?)", (symbol.upper(), _utcnow()))
    conn.close()


def remove_from_watchlist(symbol: str):
    conn = _get_conn()
    conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))
    conn.close()


def get_watchlist() -> List[str]:
    conn = _get_conn()
    rows = conn.execute("SELECT symbol FROM watchlist ORDER BY symbol ASC").fetchall()
    conn.close()
    if not rows:
        default_seed = ["AAPL", "NVDA", "MSFT", "PFE"]
        for ticker in default_seed:
            add_to_watchlist(ticker)
        return default_seed
    return [row[0] for row in rows]


def save_recommendation(rec: Dict[str, Any]):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO recommendations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        rec["symbol"].upper(),
        rec.get("horizon", "LONG_TERM_VALUE"),
        rec["action"],
        rec["target_price"],
        rec.get("trailing_pe"),
        rec.get("forward_pe"),
        rec["thesis"],
        rec.get("source", "MARKET_DISCOVERY"),
        _utcnow(),
    ))
    conn.close()


def get_recommendations() -> List[Dict[str, Any]]:
    conn = _get_conn()
    cursor = conn.execute("""
        SELECT symbol, horizon, action, target_price, trailing_pe, forward_pe, thesis, source, updated_at
        FROM recommendations
        ORDER BY updated_at DESC
        LIMIT 20
    """)
    rows = _rows_to_dicts(cursor)
    conn.close()
    return rows
