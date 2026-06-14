#!/usr/bin/env bash
# install.sh — Standalone Atelier production bootstrap.
#
# Downloads a pre-compiled Atelier binary for your platform from the
# latest GitHub release, installs it to ~/.local/bin/, and then installs
# Atelier into each detected agent host (Claude, Copilot, Cursor, Codex, etc.).
#
# Usage:
#   curl -fsSL https://github.com/atelier-ws/atelier/releases/latest/download/install.sh | bash
#
# For a comprehensive developer install (with uv, git, node, etc.) use
# scripts/local.sh from the repo checkout.
#
# Environment variables:
#   ATELIER_INSTALL_DIR     Target directory (default: ~/.local)
#   ATELIER_BIN_DIR         Binary directory (default: ~/.local/bin)
#   ATELIER_RELEASE_TAG     Release tag to install (default: latest)
#   ATELIER_DRY_RUN         If set to 1, print planned actions and exit
#   ATELIER_VERBOSE         If set to 1, show verbose output
#   ATELIER_NON_INTERACTIVE If set to 1, skip all prompts (auto-install all hosts)
#   ATELIER_NO_PATH         If set to 1, skip adding to PATH
#   ATELIER_NO_HOSTS        If set to 1, skip agent host integration install
#   ATELIER_KB_EXTRACT      If set to 1, run knowledge extraction during setup (opt-in)
#   ATELIER_KB_HOST         Extraction backend: auto | claude | codex | ollama
#   ATELIER_KB_MODEL        Model id for extraction (required for ollama)
#   ATELIER_KB_MAX_SPEND    Hard USD cap per extraction run (auto/claude)
#   ATELIER_RECALL_INDEX    SessionStart background recall indexer: on by default (set to 0 to disable)
#   ATELIER_RECALL_EMBEDDER Recall embedder: local | openai (codex) | ollama (Claude has no embeddings API)
#   ATELIER_RECALL_EMBED_MODEL  Embed model id (e.g. an ollama model name)

set -euo pipefail

# ---- paths & detection ------------------------------------------------------
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
    amd64) ARCH="x86_64" ;;
    arm64) ARCH="arm64" ;;
    aarch64) ARCH="aarch64" ;;
esac
BINARY_SUFFIX="${OS}-${ARCH}"

ATELIER_INSTALL_DIR="${ATELIER_INSTALL_DIR:-${HOME}/.local}"
ATELIER_BIN_DIR="${ATELIER_BIN_DIR:-${ATELIER_INSTALL_DIR}/bin}"
ATELIER_RELEASE_TAG="${ATELIER_RELEASE_TAG:-latest}"
ATELIER_DRY_RUN="${ATELIER_DRY_RUN:-0}"
ATELIER_VERBOSE="${ATELIER_VERBOSE:-0}"
ATELIER_NON_INTERACTIVE="${ATELIER_NON_INTERACTIVE:-0}"
ATELIER_NO_PATH="${ATELIER_NO_PATH:-0}"
ATELIER_NO_HOSTS="${ATELIER_NO_HOSTS:-0}"

if [[ "$ATELIER_RELEASE_TAG" == "latest" ]]; then
    RELEASE_BASE_URL="https://github.com/atelier-ws/atelier/releases/latest/download"
else
    RELEASE_BASE_URL="https://github.com/atelier-ws/atelier/releases/download/${ATELIER_RELEASE_TAG}"
fi
ASSET_NAME="atelier-distribution-${BINARY_SUFFIX}.tar.gz"
RELEASE_URL="${RELEASE_BASE_URL}/${ASSET_NAME}"

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
need_cmd tar

DOWNLOAD_CMD=()
if command -v curl >/dev/null 2>&1; then
    DOWNLOAD_CMD=(curl -fL --retry 3 --retry-delay 2 --connect-timeout 15)
elif command -v wget >/dev/null 2>&1; then
    DOWNLOAD_CMD=(wget -qO-)
else
    fail "Either curl or wget is required to download the Atelier binary."
fi

# ---- download & extract ------------------------------------------------------
echo ""
echo "  Atelier — Production Install"
echo "  Platform: ${BINARY_SUFFIX}"
echo "  Asset: ${ASSET_NAME}"
echo ""

if [[ "$ATELIER_DRY_RUN" == "1" ]]; then
    echo "  [dry-run] ${DOWNLOAD_CMD[*]} $RELEASE_URL > /tmp/${ASSET_NAME}"
    echo "  [dry-run] tar -xzf /tmp/${ASSET_NAME} -C $ATELIER_INSTALL_DIR"
    echo "  [dry-run] Binaries would be installed to: $ATELIER_BIN_DIR"
    echo ""
    exit 0
fi

mkdir -p "$ATELIER_BIN_DIR"
TMP_ARCHIVE="$(mktemp -t atelier-binaries.XXXXXX.tar.gz)"
trap 'rm -f "$TMP_ARCHIVE"' EXIT

verbose "Downloading from: $RELEASE_URL"
if ! "${DOWNLOAD_CMD[@]}" "$RELEASE_URL" > "$TMP_ARCHIVE"; then
    fail "Could not download ${ASSET_NAME}. The release may not include this platform asset yet: ${RELEASE_URL}"
fi

if [[ ! -s "$TMP_ARCHIVE" ]]; then
    fail "Downloaded archive is empty: ${RELEASE_URL}"
fi

tar -xzf "$TMP_ARCHIVE" -C "$ATELIER_INSTALL_DIR"

info "Distribution extracted to: ${ATELIER_INSTALL_DIR}"

# ---- ensure uv is available -------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    info "Installing uv..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    else
        wget -qO- https://astral.sh/uv/install.sh | sh
    fi
    export PATH="${HOME}/.local/bin:${PATH}"
fi

# ---- run full setup via bundle.sh (installs wheel + host integrations) ------
export PATH="${ATELIER_BIN_DIR}:${PATH}"
BUNDLE_SH="${ATELIER_INSTALL_DIR}/scripts/bundle.sh"
if [[ "$ATELIER_NO_HOSTS" != "1" && -f "$BUNDLE_SH" ]]; then
    SETUP_ARGS=()
    [[ "$ATELIER_DRY_RUN" == "1" ]] && SETUP_ARGS+=(--dry-run)
    [[ "$ATELIER_NON_INTERACTIVE" == "1" ]] && SETUP_ARGS+=(--non-interactive)
    ATELIER_INSTALL_DIR="$ATELIER_INSTALL_DIR" \
    ATELIER_BIN_DIR="$ATELIER_BIN_DIR" \
    bash "$BUNDLE_SH" "${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}"
elif [[ "$ATELIER_NO_HOSTS" == "1" ]]; then
    verbose "Skipping setup (ATELIER_NO_HOSTS=1)"
fi

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
if command -v atelier >/dev/null 2>&1 || command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q "^atelier"; then
    info "Atelier $(atelier --version 2>/dev/null || echo '') ready!"
    echo ""
    echo "  Quick start:  atelier --help"
    echo "  Init runtime: atelier init"
    echo "  Docs:         https://github.com/atelier-ws/atelier"
else
    info "Atelier installed to ${ATELIER_BIN_DIR}"
    echo ""
    echo "  Restart your shell or run:"
    echo "    export PATH=\"${ATELIER_BIN_DIR}:\$PATH\""
    echo "    atelier --help"
fi
echo ""
