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
