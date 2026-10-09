@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py %*
) else if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" app.py %*
) else (
    python app.py %*
)
exit /b %errorlevel%
