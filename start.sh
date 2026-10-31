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
elif [ -f ".venv/bin/python3" ]; then
    PYTHON_EXE=".venv/bin/python3"
elif command -v uv >/dev/null 2>&1; then
    PYTHON_EXE="uv run --python 3.14 python"
else
    echo "❌ [ERROR] Python virtual environment not found at .venv"
    echo "Please run ./setup.sh first to set up the environment."
    read -p "Press Enter to exit..." || true
    exit 1
fi

# Run application and keep terminal open if an error occurs
if ! $PYTHON_EXE main.py "$@"; then
    echo "❌ Hayamimi Polyglot terminated with an error."
    read -p "Press Enter to exit..." || true
    exit 1
fi

