@echo off
cd /d "%~dp0"
python sync.py --from-last
pause