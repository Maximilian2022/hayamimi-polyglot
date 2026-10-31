#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "======================================================="
echo "  Hayamimi Polyglot - macOS"
echo "  Real-time Multilingual Meeting Interpreter"
echo "  (100% Offline / Localhost 127.0.0.1:8844)"
echo "======================================================="

if [ -f ".venv/bin/python" ]; then
    PYTHON_EXE=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="python3"
else
    echo "[ERROR] Python virtual environment not found."
    echo "Please run ./setup.sh first."
    exit 1
fi

exec "$PYTHON_EXE" main.py "$@"

