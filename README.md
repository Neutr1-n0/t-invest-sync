# t-invest-sync

Синхронизация операций из брокера **Т-Инвестиции** в **Google Таблицу** (журнал сделок).

## Возможности

- Выгрузка операций по всем счетам (брокерский, ИИС и др.)
- Поля: дата, счёт, тип, тикер, количество, цена, сумма, комиссия, валюта
- Дедупликация по `operation_id`
- Фильтрация в Google Sheets
- Инкрементальная синхронизация (`--from-last`)
- Поддержка российских SSL-сертификатов (НУЦ Минцифры)

## Быстрый старт

1. Скопируйте `.env.example` в `.env` и заполните переменные.
2. Создайте service account в Google Cloud и расшарьте таблицу на его email.
3. Установите зависимости:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

4. Запуск:

```bash
python sync.py --from 2020-01-01
```

## Настройка Google Sheets — пошагово

Скрипт не входит в ваш Google-аккаунт как человек. Он работает от
имени сервисного аккаунта («робот»). Нужно: создать этого робота в
Console Google Cloud, скачать его ключ (`credentials.json`) и дать
ему доступ к таблице (этот шаг часто пропускают).

### Шаг 0. Что подготовить

- Аккаунт Google (Gmail)
- Браузер, желательно Chrome
- Пустая или новая Google таблица (можно создать позже)

### Шаг 1. Google Cloud Console и проект

1. Откройте https://console.cloud.google.com/ и войдите в Google-аккаунт.
2. Вверху слева — выпадающий список проектов → «Новый проект» (New Project).
3. Имя, например: `t-invest-sync`. Нажмите «Создать» и дождитесь (10–30 сек).
4. Убедитесь, что в шапке выбран именно этот проект.

Google может попросить принять условия или привязать платёжный аккаунт.
Для Google Sheets API в обычном использовании плата не взимается, но
формально billing иногда всё равно просят.

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
(значение уже стоит по умолчанию в `.env.example`). Файл в `.gitignore`
— в репозиторий не попадёт.

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

## Запуск через Docker (без venv)

Тот же скрипт можно запустить в контейнере — не нужно ставить
Python-зависимости локально, сертификат НУЦ Минцифры собирается
автоматически на этапе сборки образа (см. `docker/build_ca_bundle.py`).

1. Скопируйте `.env.example` в `.env` и заполните переменные (как в шаге 1
   выше).
2. Положите `credentials.json` (service account) в корень проекта.
3. Соберите образ и запустите:

```bash
docker build -t tinvest-sync .

docker run --rm \
  --env-file .env \
  -v "$(pwd)/credentials.json:/app/credentials.json:ro" \
  tinvest-sync --from-last
```

На Windows (PowerShell) путь монтирования пишется так:

```powershell
docker run --rm `
  --env-file .env `
  -v "${PWD}/credentials.json:/app/credentials.json:ro" `
  tinvest-sync --from-last
```

По умолчанию контейнер выполняет `--from-last`; чтобы передать другие
флаги (`--from 2020-01-01`, `--insecure`), просто укажите их вместо
`--from-last` в конце команды `docker run`.

Этот же `Dockerfile` используется в `.github/workflows/sync.yml` для
автоматического запуска по расписанию через GitHub Actions — там
переменные приходят не из `.env`, а из GitHub Secrets, но сам образ
и точка входа одинаковы для обоих случаев.

## Проблема с SSL-сертификатом

> Используете Docker? Сертификат НУЦ уже встроен в образ автоматически на этапе
> сборки (`docker/build_ca_bundle.py`) — этот раздел вас не касается, он
> относится только к запуску без Docker (нативно в venv).

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

Флаг `--insecure` отключает проверку SSL-сертификата. Используйте
только если установка сертификата невозможна.

Также можно задать переменную окружения `TINVEST_VERIFY_SSL=false`
в файле `.env`.

## Использование

```bash
# Выгрузить все операции с 2020-01-01
python sync.py --from 2020-01-01

# Выгрузить только новые операции (начиная с последней даты в таблице)
python sync.py --from-last

# Отключить проверку SSL (если сертификат НУЦ не установлен)
python sync.py --from 2020-01-01 --insecure
```

## Секреты

Не коммитьте `.env`, `credentials.json` и токены API.
