#!/usr/bin/env bash
# install.sh — Standalone Atelier production bootstrap.
#
# Downloads a pre-compiled Atelier binary for your platform from the
# latest GitHub release and installs it to ~/.local/bin/.
#
# Usage:
#   curl -fsSL https://github.com/atelier-runtime/atelier/releases/latest/download/install.sh | bash
#
# Or from the main branch (latest development build):
#   curl -fsSL https://raw.githubusercontent.com/atelier-runtime/atelier/main/scripts/install.sh | bash
#
# For a comprehensive developer install (with uv, git, node, host
# integrations, etc.) use scripts/dev.sh from the repo checkout or:
#   bash <(curl -fsSL https://raw.githubusercontent.com/atelier-runtime/atelier/main/scripts/dev.sh) --local
#
# Environment variables:
#   ATELIER_INSTALL_DIR   Target directory (default: ~/.local)
#   ATELIER_BIN_DIR       Binary directory (default: ~/.local/bin)
#   ATELIER_DRY_RUN       If set to 1, print planned actions and exit
#   ATELIER_VERBOSE       If set to 1, show verbose output
#   ATELIER_NON_INTERACTIVE If set to 1, skip all prompts
#   ATELIER_NO_PATH       If set to 1, skip adding to PATH

set -euo pipefail

# ---- paths & detection ------------------------------------------------------
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
BINARY_SUFFIX="${OS}-${ARCH}"

ATELIER_INSTALL_DIR="${ATELIER_INSTALL_DIR:-${HOME}/.local}"
ATELIER_BIN_DIR="${ATELIER_BIN_DIR:-${ATELIER_INSTALL_DIR}/bin}"
ATELIER_DRY_RUN="${ATELIER_DRY_RUN:-0}"
ATELIER_VERBOSE="${ATELIER_VERBOSE:-0}"
ATELIER_NON_INTERACTIVE="${ATELIER_NON_INTERACTIVE:-0}"
ATELIER_NO_PATH="${ATELIER_NO_PATH:-0}"

RELEASE_URL="https://github.com/atelier-runtime/atelier/releases/latest/download/atelier-binaries-${BINARY_SUFFIX}.tar.gz"

# ---- helpers -----------------------------------------------------------------
info()  { printf "  ◇  %s\n" "$*"; }
warn()  { printf "  ⚠  %s\n" "$*" >&2; }
error() { printf "  ✗  %s\n" "$*" >&2; }
fail()  { error "$*"; exit 1; }
verbose() { [[ "$ATELIER_VERBOSE" == "1" ]] && info "$*" || true; }

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

run() {
    if [[ "$ATELIER_DRY_RUN" == "1" ]]; then
        echo "  [dry-run] $*"
    else
        "$@"
    fi
}

# ---- platform check ----------------------------------------------------------
case "$OS" in
    linux|darwin) ;;
    *) fail "Unsupported OS: $OS. Atelier supports Linux and macOS." ;;
esac

case "$ARCH" in
    x86_64|aarch64|arm64) ;;
    *) fail "Unsupported architecture: $ARCH" ;;
esac

# ---- prerequisites (bash + curl/wget) ----------------------------------------
need_cmd bash

DOWNLOAD_CMD=""
if command -v curl >/dev/null 2>&1; then
    DOWNLOAD_CMD="curl -fsSL"
elif command -v wget >/dev/null 2>&1; then
    DOWNLOAD_CMD="wget -qO-"
else
    fail "Either curl or wget is required to download the Atelier binary."
fi

# ---- download & extract ------------------------------------------------------
echo ""
echo "  Atelier — Production Install"
echo "  Platform: ${BINARY_SUFFIX}"
echo ""

if [[ "$ATELIER_DRY_RUN" == "1" ]]; then
    echo "  [dry-run] $DOWNLOAD_CMD $RELEASE_URL | tar -xz -C $ATELIER_INSTALL_DIR"
    echo "  [dry-run] Binaries would be installed to: $ATELIER_BIN_DIR"
    echo ""
    exit 0
fi

mkdir -p "$ATELIER_BIN_DIR"

verbose "Downloading from: $RELEASE_URL"
$DOWNLOAD_CMD "$RELEASE_URL" | tar -xz -C "$ATELIER_INSTALL_DIR"

if [[ ! -x "${ATELIER_BIN_DIR}/atelier" ]]; then
    fail "Binary extraction failed — ${ATELIER_BIN_DIR}/atelier not found. Try ATELIER_VERBOSE=1 for details."
fi

info "Installed to: ${ATELIER_BIN_DIR}"

# ---- PATH persistence --------------------------------------------------------
if [[ "$ATELIER_NO_PATH" != "1" ]]; then
    case "$(basename "${SHELL:-bash}")" in
        zsh)  PROFILE="${ZDOTDIR:-$HOME}/.zshrc" ;;
        bash) PROFILE="$HOME/.bashrc" ;;
        fish) PROFILE="$HOME/.config/fish/config.fish" ;;
        *)    PROFILE="$HOME/.profile" ;;
    esac

    if ! echo ":$PATH:" | grep -q ":${ATELIER_BIN_DIR}:"; then
        export PATH="${ATELIER_BIN_DIR}:${PATH}"
        info "Added ${ATELIER_BIN_DIR} to PATH for this session"
    fi

    if [[ -f "$PROFILE" ]] && ! grep -q "atelier.*PATH" "$PROFILE" 2>/dev/null; then
        {
            echo ""
            echo "# >>> atelier >>>"
            echo "export PATH=\"${ATELIER_BIN_DIR}:\$PATH\""
            echo "# <<< atelier <<<"
        } >> "$PROFILE"
        info "Added to PATH in ${PROFILE/#$HOME/~}"
    fi
fi

# ---- done --------------------------------------------------------------------
echo ""
if command -v atelier >/dev/null 2>&1; then
    info "Atelier $(atelier --version 2>/dev/null || echo '') ready!"
    echo ""
    echo "  Quick start:  atelier --help"
    echo "  Init runtime: atelier init"
    echo "  Docs:         https://github.com/atelier-runtime/atelier"
else
    info "Atelier installed to ${ATELIER_BIN_DIR}"
    echo ""
    echo "  Restart your shell or run:"
    echo "    export PATH=\"${ATELIER_BIN_DIR}:\$PATH\""
    echo "    atelier --help"
fi
echo ""
