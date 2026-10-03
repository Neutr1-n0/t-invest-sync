# t-invest-sync

![version](https://img.shields.io/badge/version-1.0.0-blue)

Получение данных из **T-Invest API** и синхронизация с **Google Sheets**:
история исполненных операций, список счетов и текущие позиции портфеля.
Проект — инструмент интеграции данных; расчёты и анализ портфеля выполняются
вне t-invest-sync.

[Модель данных, API и ограничения](docs/data-model.md) · [Changelog](CHANGELOG.md)

## Возможности

- `operations` — incremental append истории исполненных операций,
  дедупликация по `operation_id`; существующая история не удаляется.
- `accounts` — полная замена snapshot всех счетов из GetAccounts,
  включая CLOSED/NEW.
- `positions` — полная замена snapshot текущих позиций;
  денежные и количественные Decimal сохраняются текстом без потери точности.
- Operations и portfolio загружаются только для `ACCOUNT_STATUS_OPEN`
  с типом `ACCOUNT_TYPE_TINKOFF` или `ACCOUNT_TYPE_TINKOFF_IIS`.
- `--from-last` использует MAX(date) отдельно по account_id с overlap один день.
- Поддержка российских SSL-сертификатов (НУЦ Минцифры)
- Запуск через Docker или локально в venv
- Автоматический запуск по расписанию через GitHub Actions

```text
T-Invest API
    ↓
t-invest-sync
    ↓
Google Sheets
    ├── operations — incremental append
    ├── accounts   — full snapshot replacement
    └── positions  — full snapshot replacement
```

Точные columns и семантика значений описаны в [модели данных](docs/data-model.md).

## Структура репозитория

```
t-invest-sync/
├── tinvest_sync/          # основной пакет
│   ├── api.py             # клиент T-Invest API
│   ├── config.py          # настройки через .env
│   ├── money.py           # конвертация денежных значений API
│   ├── sheets.py          # клиент Google Sheets
│   └── sync_service.py    # основная логика синхронизации
├── tests/                 # юнит-тесты (pytest)
├── docs/
│   └── data-model.md      # schemas, API, watermarks и ограничения
├── docker/
│   └── build_ca_bundle.py # сборка CA-бандла с сертификатом НУЦ для Docker
├── .github/workflows/
│   └── sync.yml           # GitHub Actions: schedule / workflow_dispatch
├── sync.py                # CLI точка входа
├── install_nuc_cert.py    # дополнительный Windows helper для сертификатов
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt   # + pytest для разработки
└── .env.example           # шаблон переменных окружения
```

## Быстрый старт

1. Скопируйте `.env.example` в `.env` и заполните переменные.
2. Создайте service account в Google Cloud и расшарьте таблицу на его email
   (подробно — см. раздел [«Настройка Google Sheets»](#настройка-google-sheets--пошагово)).
3. Создайте и активируйте venv, затем установите зависимости.

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

4. Подготовьте CA bundle с включённой проверкой SSL:

```bash
python docker/build_ca_bundle.py ca_bundle.pem
```

Подробнее: [TLS и CA bundle](#tls-и-ca-bundle).

5. Первый запуск: запросить operations с указанной даты и обновить оба snapshots.

```bash
python sync.py --from 2020-01-01
```

6. Регулярный запуск: повторно получить overlap operations, добавить только
   новые IDs и обновить оба snapshots.

```bash
python sync.py --from-last
```

Оба запуска записывают данные в Google Sheets. Snapshots заменяются даже
при отсутствии новых operations. `sync.bat` выполняет `python sync.py --from-last`
из каталога проекта; Python/venv должны быть доступны в текущем окружении.

## Запуск через Docker (без venv)

Не нужно ставить Python-зависимости локально — сертификат НУЦ Минцифры
встраивается в образ автоматически на этапе сборки.

1. Скопируйте `.env.example` в `.env` и заполните переменные.
2. Положите `credentials.json` (service account) в корень проекта.
3. Соберите образ и запустите:

```bash
docker build -t tinvest-sync .

# Linux/macOS
docker run --rm \
  --env-file .env \
  -e GOOGLE_SERVICE_ACCOUNT_FILE=/app/credentials.json \
  -v "$(pwd)/credentials.json:/app/credentials.json:ro" \
  tinvest-sync --from-last

# Windows (PowerShell)
docker run --rm `
  --env-file .env `
  -e GOOGLE_SERVICE_ACCOUNT_FILE=/app/credentials.json `
  -v "${PWD}/credentials.json:/app/credentials.json:ro" `
  tinvest-sync --from-last
```

По умолчанию контейнер выполняет `--from-last`. Чтобы передать другие флаги,
укажите их вместо `--from-last` в конце команды `docker run`.

## Конфигурация

Настройки берутся из окружения и `.env` через `python-dotenv`; уже заданное
окружение имеет приоритет. Шаблон: [.env.example](.env.example).

| Переменная | Назначение | Default |
|---|---|---|
| `TINVEST_TOKEN` | Токен T-Invest API с правами чтения | Обязателен |
| `GOOGLE_SPREADSHEET_ID` | ID целевой Google Spreadsheet | Обязателен |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Путь к существующему JSON-ключу service account | `credentials.json` |
| `DEFAULT_FROM_DATE` | Начало operations без explicit `--from`; fallback при отсутствии watermark с `--from-last` | `2019-01-01T00:00:00Z` |
| `TINVEST_VERIFY_SSL` | Проверка SSL для T-Invest; оставляйте включённой | `true` |

Относительный путь credentials считается от рабочей директории. В Docker
mount и переменная должны указывать на один и тот же файл внутри контейнера.
`GOOGLE_CREDENTIALS_JSON` — secret workflow, а не настройка приложения:
workflow записывает из него файл credentials.

Названия листов, eligibility и API endpoint заданы в коде и не настраиваются
через env. Подробнее о выборе CA: [TLS и CA bundle](#tls-и-ca-bundle).

## Автоматический запуск через GitHub Actions

Используется [.github/workflows/sync.yml](.github/workflows/sync.yml).
Triggers: `schedule` — каждый понедельник в 06:00 UTC (09:00 МСК),
и `workflow_dispatch` — ручной запуск. `push`/`pull_request` triggers отсутствуют.
Scheduled workflow выполняется на default branch; при ручном запуске можно
выбрать branch/ref. Переменные приходят не из `.env`, а из GitHub Secrets — образ
и точка входа одинаковы для локального и автоматического запуска.

Execution path: checkout → запись credentials.json → Docker build →
`docker run --from-last` → cleanup credentials с `if: always()`.
JSON-файл монтируется read-only в `/app/credentials.json`;
`GOOGLE_SERVICE_ACCOUNT_FILE` указывает на этот путь. Job работает на
`ubuntu-latest`, timeout — 10 минут. `DEFAULT_FROM_DATE` и `TINVEST_VERIFY_SSL`
workflow не передаёт: используются defaults приложения и CA bundle образа.
Concurrency group не задана: запуски могут пересекаться.

### Настройка секретов

Перед первым запуском добавьте в репозитории GitHub:
**Settings → Secrets and variables → Actions → New repository secret**

| Секрет | Значение |
|---|---|
| `TINVEST_TOKEN` | Токен T-Invest API |
| `GOOGLE_SPREADSHEET_ID` | ID Google Таблицы |
| `GOOGLE_CREDENTIALS_JSON` | Содержимое `credentials.json` целиком (JSON-текст) |

После этого workflow запустится по расписанию автоматически. Для ручного
запуска: вкладка **Actions** → **T-Invest sync** → **Run workflow**.

## Настройка Google Sheets — пошагово

Скрипт работает от имени сервисного аккаунта («робот»), а не от вашего
Google-аккаунта. Нужно: создать этого робота в Google Cloud, скачать его
ключ (`credentials.json`) и дать ему доступ к таблице (этот шаг часто
пропускают).

### Шаг 0. Что подготовить

- Аккаунт Google (Gmail)
- Браузер, желательно Chrome
- Пустая или новая Google таблица (можно создать позже)

### Шаг 1. Google Cloud Console и проект

1. Откройте https://console.cloud.google.com/ и войдите в Google-аккаунт.
2. Вверху слева — выпадающий список проектов → «Новый проект» (New Project).
3. Имя, например: `t-invest-sync`. Нажмите «Создать» и дождитесь (10–30 сек).
4. Убедитесь, что в шапке выбран именно этот проект.

Google может попросить привязать платёжный аккаунт. Для Google Sheets API
в обычном использовании плата не взимается, но billing иногда всё равно просят.

### Шаг 2. Включить Google Sheets API

1. В меню слева: «APIs & Services» → «Library»
   (или https://console.cloud.google.com/apis/library).
2. В поиске: `Google Sheets API`.
3. Откройте Google Sheets API и нажмите «Enable» / «Включить».

### Шаг 3. Service Account (сервисный аккаунт)

1. «APIs & Services» → «Credentials»
   (или https://console.cloud.google.com/apis/credentials).
2. Вверху: «+ CREATE CREDENTIALS» → «Service account».
3. Заполните:
   - Service account name: `t-invest-sync-bot`
   - Service account ID — подставится сам
4. «Create and Continue».
5. Grant access (роль) — можно пропустить → «Continue» → «Done».

### Шаг 4. Скачать JSON-ключ

1. На странице Credentials в блоке «Service Accounts» кликните по
   созданному аккаунту (`t-invest-sync-bot@...`).
2. Вкладка «Keys» (Ключи) → «Add key» → «Create new key».
3. Тип: JSON → «Create». Файл скачается автоматически.
4. Переименуйте файл и положите в корень проекта как `credentials.json`.

В `.env` это соответствует переменной `GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json`
(значение уже стоит по умолчанию в `.env.example`). Файл в `.gitignore` —
в репозиторий не попадёт.

### Шаг 5. Email робота — обязательно

Откройте `credentials.json` и найдите поле `client_email`:

```
"client_email": "t-invest-sync-bot@ваш-проект.iam.gserviceaccount.com"
```

Скопируйте этот email — он понадобится для доступа к таблице.

### Шаг 6. Google таблица и доступ

1. Создайте таблицу: https://sheets.google.com → Пустая таблица.
2. Откройте «Настройки доступа» / Share.
3. Вставьте `client_email` из JSON, роль — Редактор (Editor).
4. Снимите галочку «Уведомить», если мешает → «Готово».

Без этого шага будет ошибка «The caller does not have permission».

### Шаг 7. ID таблицы в .env

ID — длинная строка в URL таблицы между `/d/` и `/edit`:

```
https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz1234567890/edit

GOOGLE_SPREADSHEET_ID=1AbCdEfGhIjKlMnOpQrStUvWxYz1234567890
```

### Частые затруднения

| Проблема | Решение |
|---|---|
| Не вижу «Service account» | Credentials → Create credentials → Service account (не «API key», не «OAuth») |
| Скачался не JSON | При создании ключа выберите именно JSON |
| «Permission denied» при запуске | Расшарьте таблицу на `client_email`, роль Editor |
| «API has not been used» | Включите Google Sheets API в Library для того же проекта, где создан service account |
| Просят billing | Проверьте требования выбранного Google Cloud проекта и его настройки billing |
| Путаница OAuth vs Service Account | Нужен Service Account + JSON, не «OAuth client ID» |

## Тестирование

В проекте есть юнит-тесты API mapping, snapshots и orchestration —
без обращений к реальному API, таблицам или токенам.

### Что покрыто

- `test_verify_ssl.py` — логика `Settings.from_env()`: выбор значения
  `verify_ssl` в зависимости от переменных окружения и наличия `ca_bundle.pem`;
  прокидывание флага в `requests.Session` через `TInvestClient`.
- `test_sheets_dates.py` — конвертация дат из Google Sheets serial number
  в ISO-строку, per-account MAX(date), UTC и пропуск некорректных строк.
- `test_api.py` — Account/Operation mapping, cursor pagination,
  missing nextCursor и cursor cycle guards.
- `test_api_portfolio.py` — Position mapping, optional поля, currency,
  Decimal precision и исключение virtualPositions.
- `test_money.py` — существующая float-конвертация operations и выбор currency.
- `test_sheets_accounts.py` / `test_sheets_positions.py` — schemas, sorting,
  None/zero, точный Decimal text, создание листов, empty snapshots,
  stale-tail clearing и ошибки записи.
- `test_sync_service.py` — eligibility, overlap/fallback/explicit date,
  dedup и порядок API/Sheets вызовов при успехе и ошибках.

### Запуск

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -v
```

Тесты используют искусственные данные и mocked API/Sheets clients;
реальные credentials для них не требуются. Тесты request shape не заменяют
проверку серверного поведения Sheets.

### Что не покрыто тестами

Интеграционные сценарии (реальный вызов T-Invest API, реальная запись в
Google Sheets) намеренно вынесены за рамку автоматических тестов — они
требуют реальных токенов. Ручной integration run через Docker или Actions
выполняет записи в целевую таблицу, включая замену snapshots; согласуйте
целевую таблицу и исключите одновременные запуски перед такой проверкой.

## TLS и CA bundle

> Используете Docker или GitHub Actions? Сертификат НУЦ уже встроен в образ
> автоматически на этапе сборки (`docker/build_ca_bundle.py`). SSL verification
> остаётся включённой.

API Т-Инвестиций использует сертификат, выпущенный **НУЦ Минцифры**
(`Russian Trusted Sub CA`). Если используемый CA bundle не доверяет цепочке
этого удостоверяющего центра, возможна ошибка:

```
SSL: CERTIFICATE_VERIFY_FAILED certificate verify failed: self signed certificate in certificate chain
```

### Сборка bundle для локального запуска

```bash
python docker/build_ca_bundle.py ca_bundle.pem
```

Этот же скрипт используется в Docker: он скачивает Russian Trusted Root CA
и Russian Trusted Sub CA с проверкой TLS и добавляет их к bundle certifi.
Bundle создаётся в корне проекта/`/app`; его содержимое не является secrets.
Settings автоматически использует этот файл, если SSL verification включена.
Без файла применяется стандартный CA bundle requests (обычно certifi),
а не автоматическое чтение системного хранилища Windows.

`install_nuc_cert.py` — существующий Windows helper: создаёт bundle и импортирует
сертификаты в CurrentUser. Он также содержит fallback скачивания без TLS
verification; для обычной подготовки используйте production script выше.
Установка только в системное хранилище сама по себе не гарантирует доверие requests.

`--insecure` и `TINVEST_VERIFY_SSL` со значениями `false`/`0`/`no` поддерживаются
кодом и отключают проверку сертификата T-Invest. Они не рекомендуются как
решение TLS-проблемы; оставляйте verification включённой и проверяйте CA bundle.
Флаг `--insecure` имеет приоритет над настройкой env и наличием bundle.

## Справка по флагам

```
python sync.py [--from DATE] [--from-last] [--insecure]

  --from DATE     Начало operations (YYYY-MM-DD или ISO datetime).
  --from-last     MAX(date) по account_id минус 1 день; без watermark
                  eligible account начинает с DEFAULT_FROM_DATE.
  --insecure      Отключить проверку SSL-сертификата.
                  Поддерживается, но не рекомендуется.
```

`--from` и `--from-last` взаимно исключаются. Без обоих флагов operations
запрашиваются с `DEFAULT_FROM_DATE`. Даты без timezone трактуются как UTC,
ISO datetime с timezone приводится к UTC. Флаги периода относятся только
к operations: accounts/positions всегда отражают текущий snapshot.
Подробности overlap: [Watermarks](docs/data-model.md#watermarks-и-from-last).

## Ограничения данных

Operations append-only с текущим dedup key `operation_id`; reconciliation и
checkpoints не реализованы. Sheets writes последовательные и не транзакционные,
параллельные sync runs не сериализованы. Абсолютная полнота истории может
требовать сверки с broker report. Подробности и сценарии partial writes:
[Ограничения](docs/data-model.md#ограничения).

## Безопасность

- Никогда не коммитьте `.env` и `credentials.json` — они в `.gitignore`.
- Токен T-Invest API создавайте с минимальными правами (read-only).
- В GitHub Actions секреты храните в **Settings → Secrets**, не в коде
  и не в переменных окружения workflow напрямую.
- Оставляйте SSL verification включённой; подготовьте CA bundle вместо
  отключения проверки сертификатов.
