#!/usr/bin/env bash
# ==============================================================================
# Hayamimi Polyglot - Setup & Updater for macOS (12 Monterey ~ 15 Sequoia)
# Zero Admin Required. Automatically avoids iCloud Drive sync folders.
# ==============================================================================

set -e

echo "======================================================="
echo "  🎙️🌐 Hayamimi Polyglot - macOS Setup & Updater"
echo "======================================================="

# 1. Smart Install Path Detection (Avoid iCloud Drive)
DOCS="$HOME/Documents"
DEFAULT_PATH="$HOME/Documents/hayamimi-polyglot"

# Detect if Documents is synced to iCloud Drive
if [ -L "$DOCS" ] || [[ "$DOCS" == *"com~apple~CloudDocs"* ]] || [ -d "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents" ]; then
    echo "💡 Detected iCloud Drive Documents sync. Using home directory to avoid heavy sync."
    DEFAULT_PATH="$HOME/hayamimi-polyglot"
fi

INSTALL_PATH="${1:-$DEFAULT_PATH}"
echo "📁 Install target: $INSTALL_PATH"
mkdir -p "$INSTALL_PATH"

# 2. Verify / Install uv
if ! command -v uv >/dev/null 2>&1; then
    echo "⬇️ Installing uv (Rust-based fast Python environment manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# 3. Create or Clean-Rebuild Python 3.14 Virtual Environment
if [ -d "$INSTALL_PATH/.venv" ]; then
    echo "🔄 Existing Python environment detected."
    echo "⚡ Clean-rebuilding virtual environment (--clear)..."
    echo "   (uv caches wheels locally, so rebuild takes only 1-2 seconds with 0 re-downloads)"
    uv venv --clear "$INSTALL_PATH/.venv" --python 3.14
else
    echo "🐍 Creating Python 3.14 virtual environment (.venv)..."
    uv venv "$INSTALL_PATH/.venv" --python 3.14
fi

# 4. Copy project files if installing to different directory
CURRENT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ "$CURRENT_DIR" != "$INSTALL_PATH" ] && [ -f "$CURRENT_DIR/main.py" ]; then
    echo "📋 Copying application files..."
    cp -R "$CURRENT_DIR/core" "$INSTALL_PATH/"
    cp -R "$CURRENT_DIR/ui" "$INSTALL_PATH/"
    cp -R "$CURRENT_DIR/dicts" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/main.py" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/config.json" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/requirements.txt" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/start.sh" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/version.txt" "$INSTALL_PATH/"
    chmod +x "$INSTALL_PATH/start.sh"
fi

# 5. Install Dependencies (Synchronize with Upgrade)
echo "📦 Synchronizing dependencies (PySide6, sherpa-onnx, ctranslate2)..."
uv pip install -r "$INSTALL_PATH/requirements.txt" --python "$INSTALL_PATH/.venv/bin/python" --upgrade

# 6. Prepare models directory
mkdir -p "$INSTALL_PATH/models"

# 7. Create Desktop Shortcut
DESKTOP="$HOME/Desktop"
if [ -d "$DESKTOP" ]; then
    SHORTCUT="$DESKTOP/Hayamimi Polyglot.command"
    cat <<EOF > "$SHORTCUT"
#!/usr/bin/env bash
cd "$INSTALL_PATH"
./start.sh
EOF
    chmod +x "$SHORTCUT"
    echo "🖥️ Desktop launcher created: $SHORTCUT"
fi

echo "======================================================="
echo "🎉 Setup successfully completed!"
echo "You can launch Hayamimi Polyglot from Desktop or:"
echo "  cd $INSTALL_PATH && ./start.sh"
echo "======================================================="

