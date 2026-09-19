import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb

from backend.app.config import settings

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


def _rows_to_dicts(cursor) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cursor.description]
    return [{col: val for col, val in zip(cols, row)} for row in cursor.fetchall()]


def _get_conn():
    global _SCHEMA_READY
    conn = duckdb.connect(str(_db_path()))
    if _SCHEMA_READY:
        return conn
    with _SCHEMA_LOCK:
        if not _SCHEMA_READY:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_events (
                    id VARCHAR PRIMARY KEY,
                    event_type VARCHAR NOT NULL,
                    symbol VARCHAR,
                    payload VARCHAR,
                    created_at TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS portfolio_chat_messages (
                    id VARCHAR PRIMARY KEY,
                    role VARCHAR NOT NULL,
                    content VARCHAR NOT NULL,
                    created_at TIMESTAMP
                );
            """)
            _SCHEMA_READY = True
    return conn


def log_agent_event(event_type: str, *, symbol: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> str:
    event_id = str(uuid.uuid4())[:12]
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO agent_events (id, event_type, symbol, payload, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (event_id, event_type, symbol, json.dumps(payload or {}, default=str), _utcnow()),
    )
    return event_id


def recent_agent_events(*, limit: int = 50, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = _get_conn()
    if event_type:
        rows = _rows_to_dicts(
            conn.execute(
                """
                SELECT id, event_type, symbol, payload, created_at
                FROM agent_events
                WHERE event_type = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (event_type, limit),
            )
        )
    else:
        rows = _rows_to_dicts(
            conn.execute(
                """
                SELECT id, event_type, symbol, payload, created_at
                FROM agent_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        )
    for row in rows:
        raw = row.get("payload")
        if isinstance(raw, str):
            try:
                row["payload"] = json.loads(raw)
            except json.JSONDecodeError:
                row["payload"] = {}
    return rows


def save_portfolio_chat_message(role: str, content: str) -> None:
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO portfolio_chat_messages (id, role, content, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (str(uuid.uuid4())[:12], role, content, _utcnow()),
    )


def portfolio_chat_history(*, limit: int = 40) -> List[Dict[str, Any]]:
    conn = _get_conn()
    rows = _rows_to_dicts(
        conn.execute(
            """
            SELECT role, content, created_at
            FROM portfolio_chat_messages
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
    )
    return list(reversed(rows))


def agent_memory_stats() -> Dict[str, int]:
    conn = _get_conn()
    events = conn.execute("SELECT COUNT(*) FROM agent_events").fetchone()[0]
    chats = conn.execute("SELECT COUNT(*) FROM portfolio_chat_messages").fetchone()[0]
    try:
        orders = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE is_dry_run = true"
        ).fetchone()[0]
    except Exception:
        orders = 0
    return {
        "agent_events": int(events),
        "portfolio_chat_messages": int(chats),
        "paper_orders": int(orders),
    }
