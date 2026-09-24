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
