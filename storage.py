"""Shared persistence for finance and auction data.

Production uses PostgreSQL when DATABASE_URL is set. Local development falls
back to one SQLite database file; both features share the same database.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_LOCK = threading.RLock()
_SQLITE_PATH = Path(os.getenv("SQLITE_PATH", "app.db"))


def _postgres_url() -> str | None:
    value = os.getenv("DATABASE_URL", "").strip()
    return value or None


@contextmanager
def connection() -> Iterator[Any]:
    url = _postgres_url()
    if url:
        import psycopg
        conn = psycopg.connect(url)
    else:
        conn = sqlite3.connect(_SQLITE_PATH, timeout=30)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize() -> None:
    with _LOCK, connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS app_state ("
            "state_key VARCHAR(255) PRIMARY KEY, payload TEXT NOT NULL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS auction_items ("
            "item_id VARCHAR(255) PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS auction_snapshots ("
            "item_id VARCHAR(255) PRIMARY KEY, name TEXT NOT NULL, lots TEXT NOT NULL, "
            "total INTEGER NOT NULL, refreshed_at VARCHAR(64) NOT NULL)"
        )


def _placeholder() -> str:
    return "%s" if _postgres_url() else "?"


def get_json(key: str, default: Any = None) -> Any:
    initialize()
    with _LOCK, connection() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT payload FROM app_state WHERE state_key = {_placeholder()}", (key,))
        row = cur.fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return default


def set_json(key: str, value: Any) -> None:
    initialize()
    payload = json.dumps(value, ensure_ascii=False)
    with _LOCK, connection() as conn:
        cur = conn.cursor()
        if _postgres_url():
            cur.execute(
                "INSERT INTO app_state (state_key, payload) VALUES (%s, %s) "
                "ON CONFLICT (state_key) DO UPDATE SET payload = EXCLUDED.payload",
                (key, payload),
            )
        else:
            cur.execute(
                "INSERT INTO app_state (state_key, payload) VALUES (?, ?) "
                "ON CONFLICT(state_key) DO UPDATE SET payload=excluded.payload",
                (key, payload),
            )


def replace_auction_items(items: list[Any]) -> None:
    initialize()
    rows = [(str(i.id), str(i.name), str(i.path)) for i in items]
    with _LOCK, connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM auction_items")
        marker = "%s" if _postgres_url() else "?"
        cur.executemany(
            f"INSERT INTO auction_items (item_id, name, path) VALUES ({marker}, {marker}, {marker})",
            rows,
        )


def load_auction_items() -> list[tuple[str, str, str]]:
    initialize()
    with _LOCK, connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT item_id, name, path FROM auction_items ORDER BY name")
        return [(str(row[0]), str(row[1]), str(row[2])) for row in cur.fetchall()]


def upsert_auction_snapshot(item_id: str, name: str, lots: list[dict[str, Any]], total: int) -> str:
    initialize()
    refreshed_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(lots, ensure_ascii=False)
    with _LOCK, connection() as conn:
        cur = conn.cursor()
        if _postgres_url():
            cur.execute(
                "INSERT INTO auction_snapshots (item_id, name, lots, total, refreshed_at) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (item_id) DO UPDATE SET "
                "name=EXCLUDED.name, lots=EXCLUDED.lots, total=EXCLUDED.total, refreshed_at=EXCLUDED.refreshed_at",
                (item_id, name, payload, total, refreshed_at),
            )
        else:
            cur.execute(
                "INSERT INTO auction_snapshots (item_id, name, lots, total, refreshed_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(item_id) DO UPDATE SET "
                "name=excluded.name, lots=excluded.lots, total=excluded.total, refreshed_at=excluded.refreshed_at",
                (item_id, name, payload, total, refreshed_at),
            )
    return refreshed_at


def load_auction_snapshot(item_id: str) -> dict[str, Any] | None:
    initialize()
    with _LOCK, connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT item_id, name, lots, total, refreshed_at FROM auction_snapshots WHERE item_id = {_placeholder()}",
            (item_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    try:
        lots = json.loads(row[2])
    except (TypeError, json.JSONDecodeError):
        lots = []
    return {"item_id": str(row[0]), "name": str(row[1]), "lots": lots, "total": int(row[3]), "refreshed_at": str(row[4])}
