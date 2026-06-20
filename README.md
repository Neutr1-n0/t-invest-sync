# t-invest-sync

![version](https://img.shields.io/badge/version-1.0.0-blue)

Синхронизация операций из брокера **Т-Инвестиции** в **Google Таблицу** (журнал сделок).

[Changelog](CHANGELOG.md)

## Возможности

- Выгрузка операций по всем счетам (брокерский, ИИС и др.)
- Поля: дата, счёт, тип, тикер, количество, цена, сумма, комиссия, валюта
- Дедупликация по `operation_id`
- Инкрементальная синхронизация (`--from-last`)
- Поддержка российских SSL-сертификатов (НУЦ Минцифры)
- Запуск через Docker или локально в venv
- Автоматический запуск по расписанию через GitHub Actions

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
├── docker/
│   └── build_ca_bundle.py # сборка CA-бандла с сертификатом НУЦ для Docker
├── .github/workflows/
│   └── sync.yml           # GitHub Actions: запуск по расписанию
├── sync.py                # CLI точка входа
├── install_nuc_cert.py    # установка сертификата НУЦ в Windows (для venv-запуска)
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt   # + pytest для разработки
└── .env.example           # шаблон переменных окружения
```

## Быстрый старт

1. Скопируйте `.env.example` в `.env` и заполните переменные.
2. Создайте service account в Google Cloud и расшарьте таблицу на его email
   (подробно — см. раздел [«Настройка Google Sheets»](#настройка-google-sheets--пошагово)).
3. Установите зависимости:

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

4. Первый запуск (загрузить всё с определённой даты):

```bash
python sync.py --from 2020-01-01
```

5. Последующие запуски (только новые операции):

```bash
python sync.py --from-last
```

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
  -v "$(pwd)/credentials.json:/app/credentials.json:ro" \
  tinvest-sync --from-last

# Windows (PowerShell)
docker run --rm `
  --env-file .env `
  -v "${PWD}/credentials.json:/app/credentials.json:ro" `
  tinvest-sync --from-last
```

По умолчанию контейнер выполняет `--from-last`. Чтобы передать другие флаги,
укажите их вместо `--from-last` в конце команды `docker run`.

## Автоматический запуск через GitHub Actions

`Dockerfile` используется в `.github/workflows/sync.yml` для запуска по
расписанию. Переменные приходят не из `.env`, а из GitHub Secrets — образ
и точка входа одинаковы для локального и автоматического запуска.

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
| Просят billing | Создайте billing account — для Sheets при личном использовании обычно $0 |
| Путаница OAuth vs Service Account | Нужен Service Account + JSON, не «OAuth client ID» |

## Тестирование

В проекте есть юнит-тесты на логику конфигурации и работы с датами —
без обращений к реальному API, таблицам или токенам.

### Что покрыто

- `test_verify_ssl.py` — логика `Settings.from_env()`: выбор значения
  `verify_ssl` в зависимости от переменных окружения и наличия `ca_bundle.pem`;
  прокидывание флага в `requests.Session` через `TInvestClient`.
- `test_sheets_dates.py` — конвертация дат из Google Sheets serial number
  в ISO-строку (`_normalize_sheet_date`), корректность выбора последней даты
  из таблицы через `get_last_operation_date`.

### Запуск

```bash
pip install -r requirements-dev.txt
pytest -v
```

Ожидаемый результат: все тесты зелёные, один FutureWarning от `google-api-core`
про Python 3.10 — безвредный.

### Что не покрыто тестами

Интеграционные сценарии (реальный вызов T-Invest API, реальная запись в
Google Sheets) намеренно вынесены за рамку автоматических тестов — они
требуют реальных токенов. Для проверки используйте ручной запуск:

```bash
python sync.py --from-last
```

## Проблема с SSL-сертификатом

> Используете Docker или GitHub Actions? Сертификат НУЦ уже встроен в образ
> автоматически на этапе сборки (`docker/build_ca_bundle.py`) — этот раздел
> вас не касается.

API Т-Инвестиций использует сертификат, выпущенный **НУЦ Минцифры**
(`Russian Trusted Sub CA`). Если на вашем компьютере не установлен
корневой сертификат этого удостоверяющего центра, вы получите ошибку:

```
SSL: CERTIFICATE_VERIFY_FAILED certificate verify failed: self signed certificate in certificate chain
```

### Решение 1 (рекомендуемое): установить сертификат НУЦ

```bash
python install_nuc_cert.py
```

Скрипт скачает и установит корневой сертификат в системное хранилище
текущего пользователя. После этого `sync.py` будет работать без
дополнительных флагов.

### Решение 2 (временное): отключить проверку SSL

```bash
python sync.py --from 2020-01-01 --insecure
```

Флаг `--insecure` отключает проверку SSL-сертификата. Используйте только
если установка сертификата невозможна. Также можно задать переменную
`TINVEST_VERIFY_SSL=false` в файле `.env`.

## Справка по флагам

```
python sync.py [--from DATE] [--from-last] [--insecure]

  --from DATE     Начало периода (YYYY-MM-DD или ISO datetime).
                  По умолчанию — DEFAULT_FROM_DATE из .env.
  --from-last     Начать с последней даты в таблице (минус 1 день
                  для перекрытия). Удобно для регулярных запусков.
  --insecure      Отключить проверку SSL-сертификата.
                  Только для диагностики, не используйте в постоянном режиме.
```

## Безопасность

- Никогда не коммитьте `.env` и `credentials.json` — они в `.gitignore`.
- Токен T-Invest API создавайте с минимальными правами (read-only).
- В GitHub Actions секреты храните в **Settings → Secrets**, не в коде
  и не в переменных окружения workflow напрямую.
- Флаг `--insecure` отключает проверку сертификата и делает соединение
  уязвимым к MITM — используйте только локально для диагностики.
