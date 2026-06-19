@echo off
:: Локальный запуск синхронизации (Windows, venv).
:: Для автоматического запуска по расписанию используйте GitHub Actions.
cd /d "%~dp0"
python sync.py --from-last
