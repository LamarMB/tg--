@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo Python не найден. Установите его с https://www.python.org/downloads/ ^(галочка "Add Python to PATH"^).
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  %PY% -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python bot.py
pause
