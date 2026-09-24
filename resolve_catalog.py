import json
import stalzone_auction_parser as p

NAMES = [
    "Аммиак", "Сковорода", "ткань", "Банка с пшеном", "Гнилые доски",
    "Продвинутые инструменты", "Набор специй", "Полутухлая рыба", "Клей",
    "Микроэлектроника", "Продвинутые запчасти", "Очищенное вещество 07270",
    "Пси-маячок", "Набор компонентов оружия(Мастер)", 'Блок данных "Гамма"',
    "Цветущий рыжий папоротник", "Помидор", "Чеснок", "Дрожжи", "Кастрюля",
    "Отличная тушенка", "Красная икра", "Колбасная нарезка",
]

items = p.load_items(p.DEFAULT_DB_BASE, "ru", "ru")
result = []
for query in NAMES:
    try:
        item, matches = p.find_item(items, query)
        result.append({"query": query, "id": item.id, "name": item.name, "suggestions": [m.name for m in matches[:5]]})
    except Exception as exc:
        result.append({"query": query, "error": str(exc)})
print(json.dumps(result, ensure_ascii=False, indent=2))
