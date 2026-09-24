#!/usr/bin/env python3
"""STALZONE auction parser.

Finds an item by human-readable name in EXBO's public item database and prints
first auction lots plus the minimum buyout/current price.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.error
from difflib import SequenceMatcher
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency fallback
    requests = None  # type: ignore[assignment]

DEFAULT_API_BASE = "https://eapi.stalcraft.net"
DEFAULT_DB_BASE = "https://raw.githubusercontent.com/EXBO-Studio/stalcraft-database/main"
DEFAULT_REALM = "ru"
DEFAULT_REGION = "RU"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}
_SESSION = requests.Session() if requests is not None else None
if _SESSION is not None:
    _SESSION.headers.update(DEFAULT_HEADERS)


@dataclass
class Item:
    id: str
    name: str
    path: str


def merged_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    return merged


def http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> Any:
    request_headers = merged_headers(headers)
    if _SESSION is not None:
        try:
            response = _SESSION.get(url, headers=request_headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:  # type: ignore[union-attr]
            response = exc.response
            status = response.status_code if response is not None else "unknown"
            body = response.text if response is not None else str(exc)
            raise RuntimeError(f"HTTP {status} for {url}: {body}") from exc
        except requests.RequestException as exc:  # type: ignore[union-attr]
            raise RuntimeError(f"Network error for {url}: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError(f"Invalid JSON response for {url}: {exc}") from exc

    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error for {url}: {exc}") from exc


def text_value(value: Any, lang: str) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    if value.get("type") == "text":
        return str(value.get("text") or "")
    lines = value.get("lines")
    if isinstance(lines, dict):
        return str(lines.get(lang) or lines.get("ru") or lines.get("en") or next(iter(lines.values()), ""))
    return ""


def item_id_from_path(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def load_items(db_base: str, realm: str, lang: str) -> list[Item]:
    url = f"{db_base.rstrip('/')}/{realm}/listing.json"
    listing = http_json(url)
    if not isinstance(listing, list):
        raise RuntimeError(f"Unexpected listing.json format: expected list, got {type(listing).__name__}")

    items: list[Item] = []
    for entry in listing:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("data") or "")
        if not path:
            continue
        name = text_value(entry.get("name"), lang).replace("@", " ").strip()
        item_id = item_id_from_path(path)
        if item_id:
            items.append(Item(id=item_id, name=name or item_id, path=path))
    return items


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    text = re.sub(r"[^0-9a-zа-я]+", " ", text)
    return " ".join(text.split())


def similarity(left: str, right: str) -> float:
    left_n, right_n = normalize(left), normalize(right)
    if not left_n or not right_n:
        return 0.0
    ratio = SequenceMatcher(None, left_n, right_n).ratio()
    left_words, right_words = set(left_n.split()), set(right_n.split())
    overlap = len(left_words & right_words) / max(len(left_words | right_words), 1)
    return max(ratio, overlap)


def find_item(items: list[Item], query: str, threshold: float = 0.62) -> tuple[Item, list[Item]]:
    q = normalize(query)
    if not q:
        raise RuntimeError("Введите название или ID предмета.")
    exact = [item for item in items if normalize(item.name) == q or normalize(item.id) == q]
    if exact:
        return exact[0], exact

    contains = [item for item in items if q in normalize(item.name) or q in normalize(item.id)]
    if contains:
        ranked = sorted(contains, key=lambda item: (-similarity(query, item.name), len(normalize(item.name))))
        return ranked[0], ranked[:10]

    ranked = sorted(items, key=lambda item: similarity(query, item.name), reverse=True)
    suggestions = [item for item in ranked[:10] if similarity(query, item.name) >= threshold]
    if suggestions:
        return suggestions[0], suggestions

    nearby = ", ".join(item.name for item in ranked[:5])
    suffix = f" Возможно: {nearby}." if nearby else ""
    raise RuntimeError(f"Предмет не найден: {query!r}.{suffix}")


def auction_lots(api_base: str, region: str, item_id: str, client_id: str, client_secret: str, limit: int) -> dict[str, Any]:
    params = urllib.parse.urlencode({
        "limit": limit,
        "offset": 0,
        "sort": "buyout_price",
        "order": "asc",
        "additional": "false",
    })
    url = f"{api_base.rstrip('/')}/{region}/auction/{urllib.parse.quote(item_id)}/lots?{params}"
    return http_json(
        url,
        headers={
            "Client-Id": client_id,
            "Client-Secret": client_secret,
            "Origin": "https://stalcraft.net",
            "Referer": "https://stalcraft.net/",
        },
    )


def lot_price(lot: dict[str, Any]) -> int | None:
    """Return the lot buyout price.

    For auction output and minimum price we intentionally use only buyoutPrice:
    currentPrice/startPrice are bids or starting prices, not the stack/lot buyout.
    """
    value = lot.get("buyoutPrice")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def lot_amount(lot: dict[str, Any]) -> int:
    for key in ("amount", "quantity", "count"):
        value = lot.get(key)
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 1


def lot_actual_time(lot: dict[str, Any], fetched_at: datetime) -> tuple[str, bool]:
    for key in ("updatedAt", "createdAt", "time", "timestamp", "lastUpdateTime", "lastUpdated", "endTime"):
        value = lot.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), True
    return fetched_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"), False


def sort_lots_by_amount(lots: list[Any]) -> list[dict[str, Any]]:
    dict_lots = [lot for lot in lots if isinstance(lot, dict)]
    return sorted(dict_lots, key=lot_amount, reverse=True)


def fmt_money(value: int | None) -> str:
    return "—" if value is None else f"{value:,}".replace(",", " ") + " ₽"


def fmt_amount(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " шт."


def fmt_actual_time(lot: dict[str, Any], fetched_at: datetime) -> str:
    value, from_lot = lot_actual_time(lot, fetched_at)
    return f"актуально на {value}" if not from_lot else f"актуально: {value}"


def format_lot_line(index: int, lot: dict[str, Any], fetched_at: datetime) -> str:
    price = lot_price(lot)
    amount = lot_amount(lot)
    per_item = price // amount if isinstance(price, int) and amount else None
    return (
        f"{index:2}. количество: {fmt_amount(amount)}; "
        f"цена лота: {fmt_money(price)}; "
        f"за штуку: {fmt_money(per_item)}; "
        f"{fmt_actual_time(lot, fetched_at)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Find STALZONE auction lots by item name.")
    parser.add_argument("item", nargs="+", help="Item name or item id, e.g. 'ПП-91 Кедр' or 96mj0")
    parser.add_argument("--region", default=os.getenv("STALZONE_REGION", DEFAULT_REGION), help="Auction region: RU, EU, NA, SEA, NEA")
    parser.add_argument("--realm", default=os.getenv("STALZONE_REALM", DEFAULT_REALM), help="Database realm: ru or global")
    parser.add_argument("--lang", default=os.getenv("STALZONE_LANG", "ru"), help="Item name language from database")
    parser.add_argument("--limit", type=int, default=10, help="How many lots to print, max 200")
    parser.add_argument("--api-base", default=os.getenv("STALZONE_API_BASE", DEFAULT_API_BASE))
    parser.add_argument("--db-base", default=os.getenv("STALZONE_DB_BASE", DEFAULT_DB_BASE))
    args = parser.parse_args()

    client_id = os.getenv("STALZONE_CLIENT_ID")
    client_secret = os.getenv("STALZONE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Set STALZONE_CLIENT_ID and STALZONE_CLIENT_SECRET environment variables.", file=sys.stderr)
        return 2

    query = " ".join(args.item)
    limit = max(1, min(args.limit, 200))

    try:
        items = load_items(args.db_base, args.realm, args.lang)
        item, matches = find_item(items, query)
        if len(matches) > 1:
            print("Найдено несколько совпадений, используется первое:")
            for candidate in matches[:10]:
                print(f"  - {candidate.name} ({candidate.id})")
            print()

        data = auction_lots(args.api_base, args.region.upper(), item.id, client_id, client_secret, limit)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    lots = data.get("lots") if isinstance(data, dict) else None
    if not isinstance(lots, list):
        print(f"Unexpected auction response: {json.dumps(data, ensure_ascii=False)[:1000]}", file=sys.stderr)
        return 1

    print(f"Предмет: {item.name} ({item.id})")
    print(f"Регион: {args.region.upper()}")
    print(f"Всего активных лотов: {data.get('total', len(lots))}")

    if not lots:
        print("Активных лотов не найдено.")
        return 0

    fetched_at = datetime.now(timezone.utc)
    sorted_lots = sort_lots_by_amount(lots)
    prices = [price for lot in sorted_lots for price in [lot_price(lot)] if price is not None]

    print(f"Минимальная цена выкупа среди полученных лотов: {fmt_money(min(prices) if prices else None)}")
    print("\nЛоты по количеству (от большего к меньшему):")
    for index, lot in enumerate(sorted_lots[:limit], start=1):
        print(format_lot_line(index, lot, fetched_at))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
