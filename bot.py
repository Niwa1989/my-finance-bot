
                "name": "SCraft",
                "slug": "scraft",
                "items_category_id": None
            },
            "playerok_category": {
                "id": None,
                "name": "Предметы",
                "slug": "items"
            }
        }
    }
    return ' '.join(re.findall(r'[a-zа-я0-9]+', value, flags=re.IGNORECASE))


def _items_category_id(game):
def _default_playerok_category(game):
    categories = game.get("categories") or []
    for category in categories:
        name = _normalize_search_text(category.get("name"))
        slug = _normalize_search_text(category.get("slug"))
        if "предмет" in name or slug in {"items", "item"}:
            return category.get("id")
    return None
            return category
    return categories[0] if categories else None


def _playerok_game(user_data):
    return game


def _playerok_category(user_data):
    settings = user_data.setdefault("settings", {})
    category = settings.setdefault("playerok_category", {})
    game = _playerok_game(user_data)
    category.setdefault("id", game.get("items_category_id"))
    category.setdefault("name", "Предметы")
    category.setdefault("slug", "items")
    return category


def _select_playerok_game(user_data, game):
    selected = _playerok_game(user_data)
    default_category = _default_playerok_category(game)
    selected.update({
        "id": game.get("id"),
        "name": game.get("name") or "Без названия",
        "slug": game.get("slug"),
        # Оставлено для совместимости с ранее сохранёнными данными.
        "items_category_id": default_category.get("id") if default_category else None
    })
    category = _playerok_category(user_data)
    if default_category:
        category.update({
            "id": default_category.get("id"),
            "name": default_category.get("name") or "Без категории",
            "slug": default_category.get("slug")
        })
    else:
        category.update({"id": None, "name": "Все категории", "slug": None})
    return selected


def _resolve_game(user_data):
    selected = _playerok_game(user_data)
    if selected.get("id"):
    category = _playerok_category(user_data)
    if selected.get("id") and category.get("id"):
        return selected

    payload = playerok_client.search_games(selected.get("name") or "SCraft", limit=10)
            len(_normalize_search_text(entry.get("name")))
        )
    )
    selected.update({
        "id": game.get("id"),
        "name": game.get("name") or selected.get("name"),
        "slug": game.get("slug") or selected.get("slug"),
        "items_category_id": _items_category_id(game)
    })
    return selected
    return _select_playerok_game(user_data, game)


def _product_matches(product_name, query):

def search_playerok_products(user_data, query, count):
    game = _resolve_game(user_data)
    category = _playerok_category(user_data)
    matches = []
    seen_ids = set()
    catalog_names = []
    for _ in range(PLAYEROK_SEARCH_PAGES):
        payload = playerok_client.list_items(
            game_id=game.get("id"),
            game_category_id=game.get("items_category_id"),
