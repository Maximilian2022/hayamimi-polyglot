@echo off
setlocal
cd /d "%~dp0"

echo =======================================================
echo   Hayamimi Polyglot
echo   Real-time Multilingual Meeting Interpreter
echo   (100% Offline / Localhost 127.0.0.1:8844)
echo =======================================================

if exist "%~dp0python\python.exe" (
    set "PYTHON_EXE=%~dp0python\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    echo [ERROR] Python environment not found.
    echo Please run setup.ps1 first, or use the portable package.
    pause
    exit /b 1
)

:: Run Python with error trapping
"%PYTHON_EXE%" main.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Hayamimi Polyglot encountered an error and stopped.
    pause
)
exit /b 0

