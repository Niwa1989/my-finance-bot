"""Auction use cases shared by CLI, GUI, and Telegram handlers."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import stalzone_auction_parser as parser
import storage


@dataclass(frozen=True)
class AuctionResult:
    item: parser.Item
    matches: list[parser.Item]
    lots: list[dict[str, Any]]
    total: int


def load_stack_sizes(path: str | Path = "stack_sizes.json") -> dict[str, int]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): int(value) for key, value in raw.items() if isinstance(value, int) and value in (50, 64)}


def stack_size_for(item: parser.Item, sizes: dict[str, int] | None = None) -> int | None:
    sizes = sizes if sizes is not None else load_stack_sizes()
    for key in (item.id, parser.normalize(item.name)):
        if key in sizes:
            return sizes[key]
    return None


def catalog(realm: str = parser.DEFAULT_REALM, lang: str = "ru", refresh: bool = False) -> list[parser.Item]:
    if not refresh:
        cached = storage.load_auction_items()
        if cached:
            return [parser.Item(id=item_id, name=name, path=path) for item_id, name, path in cached]
    items = parser.load_items(os.getenv("STALZONE_DB_BASE", parser.DEFAULT_DB_BASE), realm, lang)
    storage.replace_auction_items(items)
    return items


def search(query: str, region: str = parser.DEFAULT_REGION, limit: int = 200) -> AuctionResult:
    client_id = os.getenv("STALZONE_CLIENT_ID", "").strip()
    client_secret = os.getenv("STALZONE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Не заданы STALZONE_CLIENT_ID и STALZONE_CLIENT_SECRET.")
    items = catalog(os.getenv("STALZONE_REALM", parser.DEFAULT_REALM), os.getenv("STALZONE_LANG", "ru"))
    item, matches = parser.find_item(items, query)
    data = parser.auction_lots(
        os.getenv("STALZONE_API_BASE", parser.DEFAULT_API_BASE),
        region.upper(), item.id, client_id, client_secret, max(1, min(limit, 200)),
    )
    lots = data.get("lots") if isinstance(data, dict) else None
    if not isinstance(lots, list):
        raise RuntimeError("API аукциона вернул неожиданный формат.")
    return AuctionResult(item, matches, [lot for lot in lots if isinstance(lot, dict)], int(data.get("total", len(lots))))


def refresh_snapshot(item_id: str, name: str, region: str = parser.DEFAULT_REGION, limit: int = 200) -> str:
    client_id = os.getenv("STALZONE_CLIENT_ID", "").strip()
    client_secret = os.getenv("STALZONE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("STALZONE_CLIENT_ID/STALZONE_CLIENT_SECRET are required")
    data = parser.auction_lots(
        os.getenv("STALZONE_API_BASE", parser.DEFAULT_API_BASE), region.upper(), item_id,
        client_id, client_secret, max(1, min(limit, 200)),
    )
    lots = data.get("lots") if isinstance(data, dict) else None
    if not isinstance(lots, list):
        raise RuntimeError("unexpected auction API response")
    clean_lots = [lot for lot in lots if isinstance(lot, dict)]
    return storage.upsert_auction_snapshot(item_id, name, clean_lots, int(data.get("total", len(clean_lots))))


def cached_search(query: str, stale_after_seconds: int = 10800) -> tuple[AuctionResult, str, bool]:
    items = catalog(os.getenv("STALZONE_REALM", parser.DEFAULT_REALM), os.getenv("STALZONE_LANG", "ru"))
    item, matches = parser.find_item(items, query)
    snapshot = storage.load_auction_snapshot(item.id)
    if snapshot is None:
        raise RuntimeError("Кэш аукциона пока недоступен. Дождитесь следующего обновления.")
    try:
        refreshed = datetime.fromisoformat(snapshot["refreshed_at"].replace("Z", "+00:00"))
        stale = (datetime.now(timezone.utc) - refreshed.astimezone(timezone.utc)).total_seconds() > stale_after_seconds
    except (TypeError, ValueError):
        stale = True
    result = AuctionResult(item, matches, snapshot["lots"], snapshot["total"])
    return result, snapshot["refreshed_at"], stale


def mode_one_lots(lots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lots with amount 5..25 inclusive, largest amount first."""
    return sorted(
        (lot for lot in lots if 5 <= parser.lot_amount(lot) <= 25),
        key=lambda lot: (-parser.lot_amount(lot), parser.lot_price(lot) if parser.lot_price(lot) is not None else float("inf")),
    )


def cheapest_full_stack(lots: list[dict[str, Any]], stack_size: int | None) -> dict[str, Any] | None:
    """Cheapest buyout among exact full stacks; partial or unknown stacks never qualify."""
    if stack_size not in (50, 64):
        return None
    exact = [lot for lot in lots if parser.lot_amount(lot) == stack_size and parser.lot_price(lot) is not None]
    return min(exact, key=lambda lot: parser.lot_price(lot) or 0) if exact else None


def load_targets(path: str | Path = "resolved_catalog.json") -> list[dict[str, Any]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in data if isinstance(row, dict) and row.get("query")]


def format_full_stack_list(
    targets: list[dict[str, Any]] | None = None,
    sizes: dict[str, int] | None = None,
    stale_after_seconds: int = 10800,
) -> str:
    """Format every configured target from cached snapshots without live requests."""
    targets = targets if targets is not None else load_targets()
    sizes = sizes if sizes is not None else load_stack_sizes()
    lines = ["🔨 Полные стаки (кэш)"]
    freshness_values: list[str] = []
    any_stale = False
    for target in targets:
        name = str(target.get("name") or target.get("query"))
        item_id = str(target.get("id") or "")
        if not item_id:
            lines.append(f"• {name}: недоступно (ID не подтверждён)")
            continue
        size = sizes.get(item_id) or sizes.get(parser.normalize(name))
        if size not in (50, 64):
            lines.append(f"• {name}: недоступно (размер стака не подтверждён)")
            continue
        snapshot = storage.load_auction_snapshot(item_id)
        if snapshot is None:
            lines.append(f"• {name} ({size} шт.): недоступно (нет кэша)")
            continue
        freshness_values.append(snapshot["refreshed_at"])
        try:
            refreshed = datetime.fromisoformat(snapshot["refreshed_at"].replace("Z", "+00:00"))
            any_stale |= (datetime.now(timezone.utc) - refreshed.astimezone(timezone.utc)).total_seconds() > stale_after_seconds
        except (TypeError, ValueError):
            any_stale = True
        lot = cheapest_full_stack(snapshot["lots"], size)
        price = parser.fmt_money(parser.lot_price(lot)) if lot else "нет точного стака"
        lines.append(f"• {name} ({size} шт.): {price}")
    lines.append(f"Обновлено: {min(freshness_values) if freshness_values else 'недоступно'}")
    if any_stale:
        lines.append("⚠️ Часть данных устарела.")
    return "\n".join(lines)


def ambiguity_message(matches: list[parser.Item]) -> str:
    return "Возможно, вы имели в виду:\n" + "\n".join(f"• {item.name} ({item.id})" for item in matches[:5])
