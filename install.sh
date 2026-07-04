#!/usr/bin/env bash
set -euo pipefail
APP=fin

MUTED='\033[0;2m'
RED='\033[0;31m'
ORANGE='\033[38;5;214m'
GREEN='\033[0;32m'
NC='\033[0m'

usage() {
    cat <<EOF
Fin Installer

Usage: install.sh [options]

Options:
    -h, --help              Display this help message
    -v, --version <version> Install a specific version (tag, e.g., v0.1.0)
        --no-modify-path    Don't modify shell config files
    -l, --local <path>      Install from a local directory instead of GitHub

Examples:
    curl -fsSL https://raw.githubusercontent.com/looph0le/fin/main/install.sh | bash
    curl -fsSL https://raw.githubusercontent.com/looph0le/fin/main/install.sh | bash -s -- --version v0.1.0
EOF
}

requested_version=${VERSION:-}
no_modify_path=false
local_path=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        -v|--version)
            if [[ -n "${2:-}" ]]; then
                requested_version="$2"
                shift 2
            else
                echo -e "${RED}Error: --version requires a version argument${NC}"
                exit 1
            fi
            ;;
        --no-modify-path)
            no_modify_path=true
            shift
            ;;
        -l|--local)
            if [[ -n "${2:-}" ]]; then
                local_path="$2"
                shift 2
            else
                echo -e "${RED}Error: --local requires a path argument${NC}"
                exit 1
            fi
            ;;
        *)
            echo -e "${ORANGE}Warning: Unknown option '$1'${NC}" >&2
            shift
            ;;
    esac
done

# --- Python check ---
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ver=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        if [[ -n "$ver" && "$(echo "$ver" | cut -d. -f1)" -ge 3 && "$(echo "$ver" | cut -d. -f2)" -ge 11 ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}Error: Python >= 3.11 is required but not found.${NC}"
    echo -e "${MUTED}Install Python 3.11+ from https://python.org and try again.${NC}"
    exit 1
fi

echo -e "${MUTED}Using Python:${NC} $($PYTHON --version) ($($PYTHON -c 'import sys; print(sys.executable)'))"

# --- Install ---
FIN_DIR="${FIN_DIR:-$HOME/.fin}"
VENV_DIR="$FIN_DIR/venv"
BIN_DIR="$FIN_DIR/bin"

# Determine pip URL
if [ -n "$local_path" ]; then
    pip_url="$local_path"
    echo -e "\n${MUTED}Installing ${NC}$APP ${MUTED}from: ${NC}$local_path"
else
    if [ -z "$requested_version" ]; then
        pip_url="git+https://github.com/looph0le/fin.git"
        echo -e "\n${MUTED}Installing ${NC}$APP ${MUTED}from main branch${NC}"
    else
        requested_version="${requested_version#v}"
        pip_url="git+https://github.com/looph0le/fin.git@v${requested_version}"
        echo -e "\n${MUTED}Installing ${NC}$APP ${MUTED}version: ${NC}v$requested_version"
    fi
fi

pip_install() {
    local python="$1"
    local url="$2"
    shift 2
    "$python" -m pip install "$url" --quiet "$@"
}

# If already in a venv, install directly.
if [ -n "${VIRTUAL_ENV:-}" ]; then
    pip_install "$PYTHON" "$pip_url"
    BIN_DIR="$VIRTUAL_ENV/bin"
elif $PYTHON -m pip install --dry-run "$pip_url" >/dev/null 2>&1; then
    # System pip is unconstrained — use --user
    pip_install "$PYTHON" "$pip_url" --user
else
    # Externally managed (PEP 668) — create an isolated venv
    echo -e "${MUTED}Creating isolated environment in ${NC}$VENV_DIR${MUTED}...${NC}"
    "$PYTHON" -m venv "$VENV_DIR"
    mkdir -p "$BIN_DIR"
    pip_install "$VENV_DIR/bin/python" "$pip_url"
    # Symlink scripts into ~/.fin/bin
    for script in fin fin-mcp; do
        if [ -f "$VENV_DIR/bin/$script" ]; then
            ln -sf "$VENV_DIR/bin/$script" "$BIN_DIR/$script"
        fi
    done
fi

echo -e "${GREEN}✓${NC} ${MUTED}$APP installed${NC}"

# --- Ensure ~/.fin exists ---
mkdir -p "$FIN_DIR"

# --- PATH & DATABASE_URL setup ---
add_line() {
    local config_file=$1
    local line=$2
    local label=$3

    if grep -Fxq "$line" "$config_file"; then
        echo -e "  ${MUTED}Already in $config_file, skipping${NC}"
    elif [[ -w $config_file ]]; then
        echo -e "\n# fin" >> "$config_file"
        echo "$line" >> "$config_file"
        echo -e "  ${MUTED}${label} added to ${NC}$config_file"
    else
        echo -e "  ${MUTED}Manually add to $config_file:${NC}"
        echo -e "  $line"
    fi
}

DB_URL_LINE="export DATABASE_URL=\"sqlite:///$FIN_DIR/finances.db\""

XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}

current_shell=$(basename "$SHELL")
case $current_shell in
    fish)
        config_files="$HOME/.config/fish/config.fish"
    ;;
    zsh)
        config_files="${ZDOTDIR:-$HOME}/.zshrc ${ZDOTDIR:-$HOME}/.zshenv $XDG_CONFIG_HOME/zsh/.zshrc $XDG_CONFIG_HOME/zsh/.zshenv"
    ;;
    bash)
        config_files="$HOME/.bashrc $HOME/.bash_profile $HOME/.profile $XDG_CONFIG_HOME/bash/.bashrc $XDG_CONFIG_HOME/bash/.bash_profile"
    ;;
    ash|sh)
        config_files="$HOME/.ashrc $HOME/.profile /etc/profile"
    ;;
    *)
        config_files="$HOME/.bashrc $HOME/.bash_profile $XDG_CONFIG_HOME/bash/.bashrc $XDG_CONFIG_HOME/bash/.bash_profile"
    ;;
esac

found=false
for file in $config_files; do
    if [[ -f $file ]]; then
        if [[ "$no_modify_path" != "true" ]]; then
            if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
                case $current_shell in
                    fish)
                        add_line "$file" "fish_add_path $BIN_DIR" "PATH"
                    ;;
                    *)
                        add_line "$file" "export PATH=\$PATH:$BIN_DIR" "PATH"
                    ;;
                esac
            fi
            if [[ -z "${DATABASE_URL:-}" ]]; then
                add_line "$file" "$DB_URL_LINE" "DATABASE_URL"
            fi
        fi
        found=true
        break
    fi
done

if [ "$found" = false ]; then
    echo -e "  ${MUTED}No shell config found. Add to your shell rc:${NC}"
    echo -e "  export PATH=\$PATH:$BIN_DIR"
    echo -e "  $DB_URL_LINE"
fi

if [ -n "${GITHUB_ACTIONS:-}" ] && [ "${GITHUB_ACTIONS}" == "true" ]; then
    echo "$BIN_DIR" >> "$GITHUB_PATH"
fi

echo -e ""
echo -e "${MUTED}▀▀█▀▀ █▄  █ ▄▀▀▄ ▄▀▀▀ █${NC}"
echo -e "${MUTED}  █   █ █ █ █  █ ▀▀▄ █${NC}"
echo -e "${MUTED}  █   █  ▀▀ ▀  ▀ ▀▀▀ ▀${NC}"
echo -e ""
echo -e "${MUTED}Try it out:${NC}"
echo -e ""
echo -e "  fin --help         ${MUTED}# See all commands${NC}"
echo -e "  fin-mcp            ${MUTED}# Start MCP server for AI agents${NC}"
echo -e ""
echo -e "${MUTED}Docs: ${NC}https://github.com/looph0le/fin"
echo -e ""
