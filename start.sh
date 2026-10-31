#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "======================================================="
echo "  🎙️🌐 Hayamimi Polyglot - macOS (100% Offline)"
echo "  Real-time Multilingual Meeting Interpreter"
echo "  (Localhost 127.0.0.1:8844 / Zero Telemetry)"
echo "======================================================="

# Enterprise Proxy & SSL Inspection settings
export UV_SYSTEM_CERTS="${UV_SYSTEM_CERTS:-true}"
export PIP_USE_FEATURE="${PIP_USE_FEATURE:-truststore}"

# 1. Check if virtual environment already exists
if [ ! -f ".venv/bin/python" ] && [ ! -f ".venv/bin/python3" ]; then
    echo "📦 Initializing local offline environment..."
    
    # Check for uv
    UV_CMD=""
    if command -v uv >/dev/null 2>&1; then
        UV_CMD="uv"
    elif [ -f "$HOME/.local/bin/uv" ]; then
        UV_CMD="$HOME/.local/bin/uv"
    elif [ -f "./uv" ]; then
        UV_CMD="./uv"
    fi

    if [ -z "$UV_CMD" ]; then
        echo "⬇️ Installing uv (fast Python manager)..."
        curl -LsSf https://astral.sh/uv/install.sh | sh || true
        UV_CMD="$HOME/.local/bin/uv"
    fi

    if [ ! -x "$UV_CMD" ] && ! command -v "$UV_CMD" >/dev/null 2>&1; then
        echo "❌ [ERROR] uv is required to initialize the offline environment."
        echo "Please install uv or Python 3.12+."
        read -p "Press Enter to exit..." || true
        exit 1
    fi

    echo "🐍 Creating virtual environment (.venv)..."
    $UV_CMD venv .venv --python 3.12 || $UV_CMD venv .venv

    if [ -d "wheels" ]; then
        echo "📦 Installing libraries from bundled offline wheels (Zero external downloads / 100% Offline)..."
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

echo "🚀 Launching Hayamimi Polyglot..."
if ! "$PYTHON_EXE" main.py "$@"; then
    echo "❌ Hayamimi Polyglot terminated with an error."
    read -p "Press Enter to exit..." || true
    exit 1
fi
