# STALZONE auction parser

Скрипт `stalzone_auction_parser.py` ищет предмет по названию в публичной базе EXBO (`stalcraft-database`), получает id предмета и запрашивает активные лоты аукциона STALZONE.

## Что нужно

- Python 3.10+.
- Доступ к STALZONE API.
- Рекомендуется установить `requests`, чтобы скрипт использовал `requests.Session` и браузероподобные заголовки вместо fallback на `urllib`:

```powershell
python -m pip install requests
```

- Переменные окружения:
  - `STALZONE_CLIENT_ID`
  - `STALZONE_CLIENT_SECRET`

Секреты не храните в файлах проекта. В PowerShell для текущей сессии:

```powershell
$env:STALZONE_CLIENT_ID="ваш_client_id"
$env:STALZONE_CLIENT_SECRET="ваш_client_secret"
```

## Графический интерфейс

Desktop GUI на стандартной библиотеке Python находится в файле `stalzone_auction_gui.py`.

Запуск из папки проекта:

```powershell
python .\stalzone_auction_gui.py
```

В интерфейсе есть поля для названия или ID предмета, региона, лимита, realm/языка базы, а также `Client-Id` и `Client-Secret`. Credentials можно не вводить в UI, если они уже заданы через переменные окружения `STALZONE_CLIENT_ID` и `STALZONE_CLIENT_SECRET`.

Кнопка «Поиск» загружает лоты, сортирует их по количеству от большего к меньшему и показывает количество, цену выкупа лота, цену за штуку и время актуальности. Минимальная цена считается только по `buyoutPrice` среди полученных лотов. Ошибки сети, отсутствующих credentials, неверного лимита или ненайденного предмета выводятся понятным сообщением в окне.

## Запуск CLI

```powershell
python .\stalzone_auction_parser.py "ПП-91 Кедр"
```

Можно передать id предмета напрямую:

```powershell
python .\stalzone_auction_parser.py 96mj0
```

Полезные параметры:

```powershell
python .\stalzone_auction_parser.py "ПП-91 Кедр" --region RU --realm ru --limit 10
```

- `--region`: регион аукциона (`RU`, `EU`, `NA`, `SEA`, `NEA`), по умолчанию `RU`.
- `--realm`: реалм базы предметов (`ru` или `global`), по умолчанию `ru`.
- `--lang`: язык названий из базы, по умолчанию `ru`.
- `--limit`: сколько лотов вывести, по умолчанию `10`, максимум API — `200`.

## Что выводится

- найденный предмет и его id;
- общее число активных лотов из ответа API;
- полученные лоты, отсортированные по количеству от большего к меньшему;
- количество, цену выкупа лота (`buyoutPrice`), цену за штуку и время актуальности;
- минимальную цену выкупа среди полученных лотов.

Важно: API возвращает цену за весь лот/стак. Для стакающихся предметов скрипт дополнительно показывает цену за штуку: `buyoutPrice / amount`. `currentPrice` и `startPrice` не используются для минимальной цены и основного вывода.

## Источники данных

- API: `https://eapi.stalcraft.net/{region}/auction/{item}/lots`
- База предметов: `https://raw.githubusercontent.com/EXBO-Studio/stalcraft-database/main/{realm}/listing.json`

Документация Lunar указывает, что для публичных данных аукциона достаточно заголовков `Client-Id` и `Client-Secret`; OAuth `client_credentials` не обязателен.

## Telegram-бот и режимы аукциона

Файл `finance_bot.py` сохраняет все прежние финансовые функции и добавляет кнопку `🔨 Аукцион` (также команда `/auction`).

- Режим 1 показывает только лоты с количеством **5–25 включительно**, сортируя их по количеству от большего к меньшему.
- Режим 2 ищет минимальную цену только среди лотов, количество которых **точно равно** размеру стака из `stack_sizes.json`. Если точного полного стака нет, бот сообщает об этом и не подменяет его частичным лотом.
- Поиск названий нормализует регистр, `ё/е`, пробелы и пунктуацию, допускает русские опечатки и показывает варианты при неоднозначности.

## Хранилище

`storage.py` предоставляет одно общее хранилище для финансовых данных и каталога аукциона:

- в production при наличии `DATABASE_URL` используется PostgreSQL;
- локально используется SQLite-файл `app.db` (путь можно изменить через `SQLITE_PATH`);
- отдельные базы парсера и бота не создаются.

При первом чтении старый локальный `bot_data.json` автоматически переносится в общее хранилище.

## Развертывание на Render

Blueprint находится в `render.yaml`. Перед запуском задайте секреты `TELEGRAM_TOKEN`, `STALZONE_CLIENT_ID`, `STALZONE_CLIENT_SECRET`. PostgreSQL подключается к сервису через `DATABASE_URL`. Команда запуска: `gunicorn finance_bot:app`, health check: `/health`.

## Проверки

```powershell
python -m unittest discover -s tests -v
python -m py_compile storage.py auction_service.py stalzone_auction_parser.py finance_bot.py bot.py
```
