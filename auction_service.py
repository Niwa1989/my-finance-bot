"""Auction use cases shared by CLI, GUI, and Telegram handlers."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
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
        return {"default": 64}
    return {str(key): int(value) for key, value in raw.items() if isinstance(value, int) and value > 0}


def stack_size_for(item: parser.Item, sizes: dict[str, int] | None = None) -> int:
    sizes = sizes or load_stack_sizes()
    for key in (item.id, parser.normalize(item.name)):
        if key in sizes:
            return sizes[key]
    return sizes.get("default", 64)


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


def mode_one_lots(lots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lots with amount 5..25 inclusive, largest amount first."""
    return sorted(
        (lot for lot in lots if 5 <= parser.lot_amount(lot) <= 25),
        key=lambda lot: (-parser.lot_amount(lot), parser.lot_price(lot) if parser.lot_price(lot) is not None else float("inf")),
    )


def cheapest_full_stack(lots: list[dict[str, Any]], stack_size: int) -> dict[str, Any] | None:
    """Cheapest buyout among exact full stacks; partial stacks never qualify."""
    exact = [lot for lot in lots if parser.lot_amount(lot) == stack_size and parser.lot_price(lot) is not None]
    return min(exact, key=lambda lot: parser.lot_price(lot) or 0) if exact else None


def ambiguity_message(matches: list[parser.Item]) -> str:
    return "Возможно, вы имели в виду:\n" + "\n".join(f"• {item.name} ({item.id})" for item in matches[:5])
