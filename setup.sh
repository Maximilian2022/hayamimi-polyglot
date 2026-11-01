#!/usr/bin/env bash
# ==============================================================================
# Hayamimi Polyglot - Setup & Updater for macOS (14 Sonoma / 15 Sequoia)
# Non-Admin Setup. Avoids iCloud Drive sync folders automatically.
# ==============================================================================

set -e

CYAN="\033[0;36m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
BLUE="\033[0;34m"
GRAY="\033[0;90m"
NC="\033[0m"

echo -e "${CYAN}=======================================================${NC}"
echo -e "${CYAN}  🎙️🌐 Hayamimi Polyglot - macOS Setup & Updater${NC}"
echo -e "${GRAY}  Real-time Multilingual Subtitle & Translation Tool${NC}"
echo -e "${CYAN}=======================================================${NC}"

# 1. Smart Install Path Detection (Avoid iCloud Drive)
DOCS="$HOME/Documents"
DEFAULT_PATH="$HOME/Documents/hayamimi-polyglot"

if [ -L "$DOCS" ] || [[ "$DOCS" == *"com~apple~CloudDocs"* ]] || [ -d "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents" ]; then
    echo -e "${YELLOW}💡 Detected iCloud Drive Documents sync. Using $HOME/hayamimi-polyglot.${NC}"
    DEFAULT_PATH="$HOME/hayamimi-polyglot"
fi

export UV_SYSTEM_CERTS="${UV_SYSTEM_CERTS:-true}"
export PIP_USE_FEATURE="${PIP_USE_FEATURE:-truststore}"

CLI_MODE=false
CUSTOM_PATH=""

for arg in "$@"; do
    case "$arg" in
        --unattended|--cli)
            CLI_MODE=true
            ;;
        *)
            if [ -z "$CUSTOM_PATH" ] && [[ "$arg" != -* ]]; then
                CUSTOM_PATH="$arg"
            fi
            ;;
    esac
done

INSTALL_PATH="${CUSTOM_PATH:-$DEFAULT_PATH}"
echo -e "${BLUE}📁 Install target:${NC} $INSTALL_PATH"
mkdir -p "$INSTALL_PATH"

# 2. Verify / Install uv
if ! command -v uv >/dev/null 2>&1; then
    echo -e "${CYAN}⬇️ Installing uv (Python environment manager)...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo -e "${GREEN}✓ uv verified:${NC} $(command -v uv)"

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ]; then
    CURRENT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
    GUI_SCRIPT="$CURRENT_DIR/installer_gui.py"
else
    CURRENT_DIR=""
    GUI_SCRIPT=""
fi

# If running via Web one-liner (curl ... | bash), fetch installer_gui.py to isolated /tmp directory
if [ -z "$GUI_SCRIPT" ] || [ ! -f "$GUI_SCRIPT" ]; then
    echo -e "${CYAN}⬇️ Fetching latest GUI installer from remote...${NC}"
    TEMP_DIR="$(mktemp -d /tmp/hayamimi-setup-XXXXXX)"
    GUI_SCRIPT="$TEMP_DIR/installer_gui.py"
    REMOTE_URL="${HAYAMIMI_GUI_URL:-https://raw.githubusercontent.com/Maximilian2022/hayamimi-polyglot/main/installer_gui.py}"
    curl -sSfL "$REMOTE_URL" -o "$GUI_SCRIPT" || true
fi

if [ "$CLI_MODE" != "true" ] && [ -f "$GUI_SCRIPT" ]; then
    echo -e "${CYAN}🚀 Launching Hayamimi Polyglot GUI Installer (PySide6)...${NC}"
    exec uv run --python 3.14 --with PySide6 python "$GUI_SCRIPT"
fi

# ------------------------------------------------------------------------------
# CLI Fallback Mode
# ------------------------------------------------------------------------------
VENV_DIR="$INSTALL_PATH/.venv"
if [ -d "$VENV_DIR" ]; then
    echo -e "${CYAN}⚡ Rebuilding virtual environment (--clear)...${NC}"
    uv venv --clear "$VENV_DIR" --python 3.14
else
    echo -e "${CYAN}🐍 Creating Python 3.14 virtual environment (.venv)...${NC}"
    uv venv "$VENV_DIR" --python 3.14
fi

if [ -n "$CURRENT_DIR" ] && [ "$CURRENT_DIR" != "$INSTALL_PATH" ] && [ -f "$CURRENT_DIR/main.py" ]; then
    echo -e "${CYAN}📋 Copying application files...${NC}"
    cp -R "$CURRENT_DIR/core" "$INSTALL_PATH/"
    cp -R "$CURRENT_DIR/ui" "$INSTALL_PATH/"
    [ -d "$CURRENT_DIR/scripts" ] && cp -R "$CURRENT_DIR/scripts" "$INSTALL_PATH/"
    cp -R "$CURRENT_DIR/dicts" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/main.py" "$INSTALL_PATH/"
    [ -f "$CURRENT_DIR/config.default.json" ] && cp "$CURRENT_DIR/config.default.json" "$INSTALL_PATH/"
    if [ ! -f "$INSTALL_PATH/config.json" ] && [ -f "$CURRENT_DIR/config.default.json" ]; then
        cp "$CURRENT_DIR/config.default.json" "$INSTALL_PATH/config.json"
    fi
    cp "$CURRENT_DIR/requirements.txt" "$INSTALL_PATH/"
    [ -f "$CURRENT_DIR/.python-version" ] && cp "$CURRENT_DIR/.python-version" "$INSTALL_PATH/"
    [ -f "$CURRENT_DIR/installer_gui.py" ] && cp "$CURRENT_DIR/installer_gui.py" "$INSTALL_PATH/"
    [ -f "$CURRENT_DIR/test_polyglot_suite.py" ] && cp "$CURRENT_DIR/test_polyglot_suite.py" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/start.sh" "$INSTALL_PATH/"
    cp "$CURRENT_DIR/version.txt" "$INSTALL_PATH/"
    chmod +x "$INSTALL_PATH/start.sh"
fi

echo -e "${CYAN}📦 Synchronizing dependencies...${NC}"
uv pip install -r "$INSTALL_PATH/requirements.txt" --python "$INSTALL_PATH/.venv/bin/python" --upgrade

if [ -f "$INSTALL_PATH/scripts/download_models.py" ]; then
    echo -e "${CYAN}⬇️ Ensuring required AI models...${NC}"
    "$INSTALL_PATH/.venv/bin/python" "$INSTALL_PATH/scripts/download_models.py" --models-dir "$INSTALL_PATH/models"
fi

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
echo -e "${GREEN}🎉 Setup completed.${NC}"
echo -e "  ${YELLOW}cd $INSTALL_PATH && ./start.sh${NC}"
echo -e "${CYAN}=======================================================${NC}"
