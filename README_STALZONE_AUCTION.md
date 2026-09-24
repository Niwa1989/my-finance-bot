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

## Определение размеров стаков

`fill_stack_sizes.py` — отдельная утилита, которая читает цели из `resolved_catalog.json`, запрашивает до 200 живых лотов на предмет и безопасно дополняет `stack_sizes.json`. Записи каталога без `id` пропускаются с понятным сообщением. Существующие проверенные значения 50/64 сохраняются и не перезаписываются.

Консервативное правило: размер 50 или 64 принимается только при наличии как минимум двух лотов ровно такого размера, когда таких лотов строго больше, чем лотов второго допустимого размера, и ни один наблюдаемый лот не превышает кандидата. Неоднозначные данные, отсутствие доказательств и ошибки API остаются неизвестными — утилита не угадывает. Подробности по каждому предмету записываются отдельно в машинно-читаемый report JSON. Оба файла заменяются атомарно.

PowerShell (используйте собственные значения вместо placeholders; секреты не передавайте аргументами):

```powershell
$env:STALZONE_CLIENT_ID="<YOUR_CLIENT_ID>"
$env:STALZONE_CLIENT_SECRET="<YOUR_CLIENT_SECRET>"

# Только проверить результат, ничего не записывая
python .\fill_stack_sizes.py .\resolved_catalog.json --dry-run --output .\stack_sizes.json

# Записать конфигурацию и отдельный evidence report
python .\fill_stack_sizes.py .\resolved_catalog.json --output .\stack_sizes.json --report .\stack_sizes.report.json
```

Если размеры стаков статичны, проверьте результат и закоммитьте сгенерированный `stack_sizes.json` в GitHub:

```powershell
git add .\stack_sizes.json
# При необходимости также сохраните audit report:
git add .\stack_sizes.report.json
git commit -m "Update verified STALZONE stack sizes"
git push
```

## Автоматическое обновление кэша

`auction_refresh_worker.py` — отдельный Render background worker. Он запускает обновление сразу при старте, затем каждые 7200 секунд. Отдельный процесс не дублируется при масштабировании web-сервиса. Каждый предмет обновляется независимо; ошибка одного предмета логируется и не останавливает цикл или Telegram-бота.

Worker читает только разрешённые ID из `resolved_catalog.json`; запись без `id` пропускается, поэтому нерешённый предмет не подменяется выдуманным ID. Credentials берутся только из `STALZONE_CLIENT_ID` и `STALZONE_CLIENT_SECRET`.

На Render задайте credentials в разделе **Environment**, а не в коде или репозитории. Worker использует закоммиченный `stack_sizes.json` как конфигурацию. Двухчасовой worker обновляет только цены/снимки аукциона в PostgreSQL; ему не нужно генерировать или перезаписывать файлы в GitHub.

Снимки лотов и UTC-время `refreshed_at` сохраняются в общей PostgreSQL через `DATABASE_URL` (локально — SQLite). Режим 2 Telegram-бота читает только этот кэш, показывает время обновления и предупреждает, если данные старше трёх часов; при отсутствии снимка сообщает, что данные недоступны.

Локальный запуск worker:

```powershell
python .\auction_refresh_worker.py
```

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
