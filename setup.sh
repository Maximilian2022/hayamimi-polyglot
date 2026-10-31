#!/usr/bin/env bash
# ==============================================================================
# Hayamimi Polyglot - Setup & Updater for macOS (12 Monterey ~ 15 Sequoia)
# Zero Admin Required. Automatically avoids iCloud Drive sync folders.
# ==============================================================================

set -e

# ANSI Color Codes
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

echo -e "${CYAN}=======================================================${NC}"
echo -e "${CYAN}  🎙️🌐 Hayamimi Polyglot - macOS Setup & Updater${NC}"
echo -e "${GRAY}  Real-time Multilingual Simultaneous Interpretation (Zero Telemetry)${NC}"
echo -e "${CYAN}=======================================================${NC}"

# 1. Smart Install Path Detection (Avoid iCloud Drive)
DOCS="$HOME/Documents"
DEFAULT_PATH="$HOME/Documents/hayamimi-polyglot"

# Detect if Documents is synced to iCloud Drive
if [ -L "$DOCS" ] || [[ "$DOCS" == *"com~apple~CloudDocs"* ]] || [ -d "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents" ]; then
    echo -e "${YELLOW}💡 Detected iCloud Drive Documents sync. Using home directory to avoid heavy sync.${NC}"
    DEFAULT_PATH="$HOME/hayamimi-polyglot"
fi

INSTALL_PATH="${1:-$DEFAULT_PATH}"
echo -e "${BLUE}📁 Install target:${NC} $INSTALL_PATH"
mkdir -p "$INSTALL_PATH"

# 2. Verify / Install uv
if ! command -v uv >/dev/null 2>&1; then
    echo -e "${CYAN}⬇️ Installing uv (Rust-based fast Python environment manager)...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo -e "${GREEN}✓ uv verified:${NC} $(command -v uv)"

CURRENT_DIR="$(cd "$(dirname "$0")" && pwd)"
GUI_SCRIPT="$CURRENT_DIR/installer_gui.py"

# If running via Web one-liner (curl ... | bash), fetch installer_gui.py to /tmp
if [ ! -f "$GUI_SCRIPT" ]; then
    echo -e "${CYAN}⬇️ Fetching latest GUI installer from remote...${NC}"
    TEMP_DIR="/tmp/hayamimi-setup"
    mkdir -p "$TEMP_DIR"
    GUI_SCRIPT="$TEMP_DIR/installer_gui.py"
    REMOTE_URL="${HAYAMIMI_GUI_URL:-https://raw.githubusercontent.com/Maximilian2022/hayamimi-polyglot/main/installer_gui.py}"
    curl -sSfL "$REMOTE_URL" -o "$GUI_SCRIPT" || true
fi

# Launch Modern GUI Installer if GUI is available and not in CLI mode
if [ "$1" != "--cli" ] && [ "$1" != "--unattended" ] && [ -f "$GUI_SCRIPT" ]; then
    echo -e "${CYAN}🚀 Launching Hayamimi Polyglot Modern GUI Installer (PySide6)...${NC}"
    exec uv run --python 3.14 --with PySide6 python "$GUI_SCRIPT"
fi

# ------------------------------------------------------------------------------
# CLI Fallback Mode (for headless / SSH / --cli)
# ------------------------------------------------------------------------------

# 3. Create or Clean-Rebuild Python 3.14 Virtual Environment
VENV_DIR="$INSTALL_PATH/.venv"
if [ -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}🔄 Existing Python environment detected.${NC}"
    echo -e "${CYAN}⚡ Clean-rebuilding virtual environment (--clear)...${NC}"
    echo -e "${GRAY}   (uv caches wheels locally, so rebuild takes only 1-2 seconds with 0 re-downloads)${NC}"
    uv venv --clear "$VENV_DIR" --python 3.14
else
    echo -e "${CYAN}🐍 Creating Python 3.14 virtual environment (.venv)...${NC}"
    uv venv "$VENV_DIR" --python 3.14
fi
echo -e "${GREEN}✓ Python 3.14 environment ready:${NC} $VENV_DIR"

# 4. Copy project files if installing to different directory
CURRENT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ "$CURRENT_DIR" != "$INSTALL_PATH" ] && [ -f "$CURRENT_DIR/main.py" ]; then
    echo -e "${CYAN}📋 Copying application files...${NC}"
    cp -R "$CURRENT_DIR/core" "$INSTALL_PATH/"
    cp -R "$CURRENT_DIR/ui" "$INSTALL_PATH/"
    cp -R "$CURRENT_DIR/dicts" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/main.py" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/config.json" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/requirements.txt" "$INSTALL_PATH/"
    [ -f "$CURRENT_DIR/.python-version" ] && cp "$CURRENT_DIR/.python-version" "$INSTALL_PATH/"
    [ -f "$CURRENT_DIR/installer_gui.py" ] && cp "$CURRENT_DIR/installer_gui.py" "$INSTALL_PATH/"
    [ -f "$CURRENT_DIR/test_polyglot_suite.py" ] && cp "$CURRENT_DIR/test_polyglot_suite.py" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/start.sh" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/version.txt" "$INSTALL_PATH/"
    chmod +x "$INSTALL_PATH/start.sh"
fi

# 5. Install Dependencies (Synchronize with Upgrade)
echo -e "${CYAN}📦 Synchronizing dependencies (PySide6, sherpa-onnx, ctranslate2)...${NC}"
uv pip install -r "$INSTALL_PATH/requirements.txt" --python "$INSTALL_PATH/.venv/bin/python" --upgrade
echo -e "${GREEN}✓ Dependencies synchronized successfully!${NC}"

# 6. Prepare and Populate Models
MODELS_DIR="$INSTALL_PATH/models"
mkdir -p "$MODELS_DIR"

# Copy from existing local models cache if available
LOCAL_MODELS_CACHE=""
if [ -d "$CURRENT_DIR/models" ]; then
    LOCAL_MODELS_CACHE="$CURRENT_DIR/models"
elif [ -d "$HOME/hayamimi/models" ]; then
    LOCAL_MODELS_CACHE="$HOME/hayamimi/models"
fi

if [ -n "$LOCAL_MODELS_CACHE" ] && [ "$LOCAL_MODELS_CACHE" != "$MODELS_DIR" ]; then
    echo -e "${CYAN}📦 Deploying models from local cache ($LOCAL_MODELS_CACHE)...${NC}"
    BASE_MODELS=(
        "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17"
        "silero_vad.onnx"
        "mojicast-m2m100-ct2"
        "mojicast-fugumt-ja-en-ct2"
    )
    for model in "${BASE_MODELS[@]}"; do
        if [ -e "$LOCAL_MODELS_CACHE/$model" ] && [ ! -e "$MODELS_DIR/$model" ]; then
            echo -e "  -> Copying: ${model}..."
            cp -R "$LOCAL_MODELS_CACHE/$model" "$MODELS_DIR/"
        fi
    done
fi

# Download SenseVoice Small if requested or absent
SENSEVOICE_DIR="$MODELS_DIR/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
if [ ! -d "$SENSEVOICE_DIR" ] && [[ "$*" == *"--with-sense-voice"* ]]; then
    echo -e "${CYAN}🚀 Downloading SenseVoice Small Multilingual ASR model...${NC}"
    SV_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
    TAR_FILE="$MODELS_DIR/sense-voice.tar.bz2"
    if curl -L "$SV_URL" -o "$TAR_FILE"; then
        tar -xjf "$TAR_FILE" -C "$MODELS_DIR"
        rm -f "$TAR_FILE"
        echo -e "${GREEN}✓ SenseVoice Small deployed successfully!${NC}"
    else
        echo -e "${YELLOW}⚠️ Failed to download SenseVoice Small (skipping).${NC}"
    fi
fi

# 7. Create Desktop Shortcut (.command launcher)
DESKTOP="$HOME/Desktop"
if [ -d "$DESKTOP" ]; then
    SHORTCUT="$DESKTOP/Hayamimi Polyglot.command"
    cat <<EOF > "$SHORTCUT"
#!/usr/bin/env bash
cd "$INSTALL_PATH"
./start.sh
EOF
    chmod +x "$SHORTCUT"
    echo -e "${GREEN}🖥️ Desktop launcher created:${NC} $SHORTCUT"
fi

echo -e "${CYAN}=======================================================${NC}"
echo -e "${GREEN}🎉 Setup successfully completed!${NC}"
echo -e "You can launch Hayamimi Polyglot from Desktop or:"
echo -e "  ${YELLOW}cd $INSTALL_PATH && ./start.sh${NC}"
echo -e "${CYAN}=======================================================${NC}"

