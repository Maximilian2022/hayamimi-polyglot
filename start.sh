#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "======================================================="
echo "  🎙️🌐 Hayamimi Polyglot - macOS (Offline Mode)"
echo "  Real-time Multilingual Meeting Interpreter"
echo "  (Localhost 127.0.0.1:8844 / No External Telemetry)"
echo "======================================================="

# Enterprise Proxy & SSL Inspection settings
export UV_SYSTEM_CERTS="${UV_SYSTEM_CERTS:-true}"
export PIP_USE_FEATURE="${PIP_USE_FEATURE:-truststore}"

# 1. Check if virtual environment already exists
if [ ! -f ".venv/bin/python" ] && [ ! -f ".venv/bin/python3" ]; then
    echo "📦 Initializing local offline environment..."
    
    # Check for uv (bundled standalone binary first)
    UV_CMD=""
    if [ -f "./uv" ]; then
        chmod +x ./uv
        UV_CMD="./uv"
    elif command -v uv >/dev/null 2>&1; then
        UV_CMD="uv"
    elif [ -f "$HOME/.local/bin/uv" ]; then
        UV_CMD="$HOME/.local/bin/uv"
    fi

    if [ -z "$UV_CMD" ]; then
        echo "❌ [ERROR] Bundled uv executable not found."
        echo "Please ensure the portable package is fully extracted."
        read -p "Press Enter to exit..." || true
        exit 1
    fi

    # Determine Python source (bundled standalone runtime first)
    PY_FLAG=""
    if [ -f "./python/bin/python3" ]; then
        chmod +x ./python/bin/python3
        PY_FLAG="--python ./python/bin/python3"
    elif command -v python3.14 >/dev/null 2>&1; then
        PY_FLAG="--python 3.14"
    elif command -v python3 >/dev/null 2>&1; then
        PY_FLAG="--python python3"
    fi

    echo "🐍 Creating virtual environment (.venv)..."
    $UV_CMD venv .venv $PY_FLAG || $UV_CMD venv .venv

    if [ -d "wheels" ]; then
        echo "📦 Installing libraries from bundled offline wheels..."
        $UV_CMD pip install --no-index --find-links ./wheels -r requirements.txt --python .venv/bin/python
    else
        echo "📦 Installing libraries via uv..."
        $UV_CMD pip install -r requirements.txt --python .venv/bin/python
    fi
    echo "✓ Environment successfully initialized!"
fi

PYTHON_EXE=".venv/bin/python"
if [ ! -f "$PYTHON_EXE" ]; then
    PYTHON_EXE=".venv/bin/python3"
fi

if [ "$1" = "--dry-run" ]; then
    echo "✓ Environment initialization dry-run completed successfully!"
    exit 0
fi

echo "🚀 Launching Hayamimi Polyglot..."
if ! "$PYTHON_EXE" main.py "$@"; then
    echo "❌ Hayamimi Polyglot terminated with an error."
    read -p "Press Enter to exit..." || true
    exit 1
fi
