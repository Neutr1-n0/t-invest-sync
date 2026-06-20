# Changelog

Все значимые изменения в проекте документируются здесь.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).

## [Unreleased]

## [1.0.0] — 2025-09-24

Первый стабильный релиз. Проект доработан до состояния, когда он запускается
без ручного venv и работает автоматически по расписанию.

### Добавлено

- Поддержка флага `--insecure` и переменной `TINVEST_VERIFY_SSL` в `.env`
  для управления проверкой SSL-сертификата.
- Использование `ca_bundle.pem` как кастомного CA-бандла при наличии файла
  в корне проекта (автоматический приоритет перед системным хранилищем).
- `Dockerfile` для запуска без локального venv; сертификат НУЦ Минцифры
  встраивается в образ на этапе сборки (`docker/build_ca_bundle.py`).
- GitHub Actions workflow (`.github/workflows/sync.yml`) для автоматического
  запуска по расписанию с передачей секретов через GitHub Secrets.
- Юнит-тесты (`tests/`): логика `verify_ssl` в `Settings.from_env()`,
  прокидывание флага в `requests.Session`, конвертация дат из Google Sheets
  serial number в ISO-строку, корректность `get_last_operation_date`.
- `.env.example` с описанием всех переменных окружения.
- Подробный `README.md`: структура репозитория, пошаговая настройка
  Google Sheets, инструкция по Docker-запуску, секция по тестированию,
  справка по флагам CLI, раздел безопасности.

### Исправлено

- `Settings` не имела поля `verify_ssl` — вызов `Settings(verify_ssl=False)`
  из `sync.py --insecure` падал с `TypeError`.
- `TInvestClient` не применял `verify_ssl` к `requests.Session` — флаг
  существовал только в конфигурации, но не влиял на HTTP-запросы.
- `get_last_operation_date` падала с `ValueError: Invalid isoformat string`
  на датах в формате Google Sheets serial number (`45924,62396`) при русской
  локали таблицы. Исправлено через `valueRenderOption=UNFORMATTED_VALUE`
  и функцию `_normalize_sheet_date`.

### Удалено

- `cloud-proxy/` — Google Cloud Function для проксирования запросов к API
  Т-Инвестиций. Изначально создана как обходной путь для SSL-сертификата НУЦ
  в Google Apps Script. Заменена Docker-подходом; удалена как небезопасная
  (открытый эндпоинт без аутентификации, `verify=False`).

[Unreleased]: https://github.com/USERNAME/t-invest-sync/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/USERNAME/t-invest-sync/releases/tag/v1.0.0
