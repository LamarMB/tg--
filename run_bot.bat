@echo off
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
if not exist ".venv\Scripts\python.exe" (
  echo Creating environment and installing packages, wait 1-2 minutes...
  %PY% -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" bot.py
pause
exit /b
:nopython
echo.
echo Python is not installed.
echo Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in the installer, then run this file again.
echo.
pause
