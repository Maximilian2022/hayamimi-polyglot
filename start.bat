@echo off
setlocal
cd /d "%~dp0"

echo =======================================================
echo   Hayamimi Polyglot
echo   Real-time Multilingual Meeting Interpreter
echo   (100% Offline / Localhost 127.0.0.1:8844)
echo =======================================================

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    echo [ERROR] Virtual environment not found at .venv
    echo Please run setup.ps1 first.
    pause
    exit /b 1
)

start "" "%PYTHON_EXE%" main.py %*
exit /b 0

