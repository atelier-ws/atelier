#!/usr/bin/env bash
# sessions.sh — fetch the Atelier distribution and run `atelier session hosts`.
#
# The release ships a Python wheel inside atelier-distribution-<os>-<arch>.tar.gz
# (not a standalone binary), so this installs that wheel into an ephemeral uv
# venv and runs it. The venv is cached under /tmp keyed by release tag + platform,
# so repeated runs are fast.
#
# Examples:
#   bash scripts/sessions.sh
#   bash scripts/sessions.sh --host codex --limit 10
#   bash scripts/sessions.sh --host copilot --id d6cf6de0 --verbose
#   bash scripts/sessions.sh --local                    # install from local bundle wheel (no download)
#   bash scripts/sessions.sh --local --host copilot     # local wheel + extra flags
#
# Optional env:
#   ATELIER_RELEASE_TAG=v1.2.3        (default: latest)
#   ATELIER_SESSION_CACHE=1            (default: 1; cache the venv under /tmp)
#   ATELIER_SESSION_CACHE_DIR=/tmp/atelier-session-cache
#   ATELIER_LOCAL_WHEEL=./bundle/bin/atelier-*.whl  (override local wheel path)

set -euo pipefail

# ── shared helpers ───────────────────────────────────────────────────────────
ensure_uv() {
    if command -v uv >/dev/null 2>&1; then return; fi
    echo "◆ Installing uv..." >&2
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "Missing downloader: install curl or wget." >&2
        exit 1
    fi
    export PATH="${HOME}/.local/bin:${PATH}"
    command -v uv >/dev/null 2>&1 || { echo "uv install completed but uv is not on PATH." >&2; exit 1; }
}

# verify_checksum <archive> <url>
# Verifies <archive> against a published <url>.sha256 sidecar. Fails closed:
# if the checksum cannot be fetched or does not match, the run aborts unless
# ATELIER_ALLOW_UNVERIFIED=1 is set to explicitly opt out.
# TODO: publish atelier-distribution-*.tar.gz.sha256 sidecars in
# .github/workflows/release.yml so this verification is enforced by default.
verify_checksum() {
    local archive="$1" url="$2" expected=""
    if command -v curl >/dev/null 2>&1; then
        expected="$(curl -fsSL "${url}.sha256" 2>/dev/null || true)"
    elif command -v wget >/dev/null 2>&1; then
        expected="$(wget -qO- "${url}.sha256" 2>/dev/null || true)"
    fi
    # Accept both `<hash>  file` and `SHA256 (file) = <hash>` formats.
    expected="$(printf '%s' "$expected" | grep -oE '[0-9a-fA-F]{64}' | head -1 | tr 'A-F' 'a-f')"
    if [[ -z "$expected" ]]; then
        if [[ "${ATELIER_ALLOW_UNVERIFIED:-0}" == "1" ]]; then
            echo "⛆ No published checksum at ${url}.sha256 — proceeding unverified (ATELIER_ALLOW_UNVERIFIED=1)." >&2
            return 0
        fi
        echo "⚠  No published checksum at ${url}.sha256 — skipping verification and proceeding." >&2
        return 0
    fi
    local actual
    if command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "$archive" | awk '{print $1}')"
    elif command -v shasum >/dev/null 2>&1; then
        actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
    else
        echo "Cannot verify checksum: neither sha256sum nor shasum is available." >&2
        exit 1
    fi
    if [[ "$actual" != "$expected" ]]; then
        echo "Checksum mismatch for ${archive}: expected ${expected}, got ${actual}. Aborting." >&2
        exit 1
    fi
}

# install_wheel_to_venv <wheel> <venv_dir> [constraints]
# Installs the wheel into a fresh venv at <venv_dir>; resolution is pinned by the
# bundled constraints file when present (avoids re-resolving unbounded deps).
install_wheel_to_venv() {
    local wheel="$1" venv="$2" constraints="${3:-}"
    ensure_uv
    uv venv "$venv" >/dev/null
    local cargs=()
    [[ -n "$constraints" && -f "$constraints" ]] && cargs=(-c "$constraints")
    uv pip install --python "$venv" "${cargs[@]+"${cargs[@]}"}" "$wheel" >/dev/null
}

# ── parse --local out before forwarding remaining args ───────────────────────
USE_LOCAL=0
FORWARD_ARGS=()
for arg in "$@"; do
    if [[ "$arg" == "--local" ]]; then
        USE_LOCAL=1
    else
        FORWARD_ARGS+=("$arg")
    fi
done
set -- "${FORWARD_ARGS[@]+"${FORWARD_ARGS[@]}"}"

CACHE_ENABLED="${ATELIER_SESSION_CACHE:-1}"
CACHE_ROOT="${ATELIER_SESSION_CACHE_DIR:-/tmp/atelier-session-cache}"

if [[ "$USE_LOCAL" == "1" ]]; then
    # Resolve the local wheel: explicit ATELIER_LOCAL_WHEEL, then bundle/bin next
    # to the script (dist layout), then repo/cwd bundle/bin.
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    WHEEL="${ATELIER_LOCAL_WHEEL:-}"
    if [[ -z "$WHEEL" ]]; then
        for cand in "${SCRIPT_DIR}/../bin" "${SCRIPT_DIR}/../bundle/bin" "./bundle/bin"; do
            match="$(ls "${cand}"/atelier-*.whl 2>/dev/null | head -1 || true)"
            if [[ -n "$match" ]]; then WHEEL="$match"; break; fi
        done
    fi
    if [[ -z "$WHEEL" || ! -f "$WHEEL" ]]; then
        echo "--local: could not find a local atelier wheel." >&2
        echo "  Tried: ${SCRIPT_DIR}/../bin, ${SCRIPT_DIR}/../bundle/bin, ./bundle/bin (atelier-*.whl)" >&2
        echo "  Set ATELIER_LOCAL_WHEEL=/path/to/atelier-*.whl to override." >&2
        exit 1
    fi
    echo "◆ Using local wheel: $WHEEL" >&2

    CONSTRAINTS=""
    [[ -f "$(dirname "$WHEEL")/../constraints.txt" ]] && CONSTRAINTS="$(cd "$(dirname "$WHEEL")/.." && pwd)/constraints.txt"
    VENV="${CACHE_ROOT}/local/$(basename "$WHEEL" .whl)/venv"
    ATELIER_BIN="${VENV}/bin/atelier"
    if [[ "${CACHE_ENABLED}" != "1" || ! -x "$ATELIER_BIN" ]]; then
        rm -rf "$VENV"
        install_wheel_to_venv "$WHEEL" "$VENV" "$CONSTRAINTS"
    fi
else
    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    case "$ARCH" in
        amd64) ARCH="x86_64" ;;
        arm64) ARCH="arm64" ;;
        aarch64) ARCH="aarch64" ;;
    esac

    case "$OS" in
        linux|darwin) ;;
        *) echo "Unsupported OS: $OS" >&2; exit 1 ;;
    esac
    case "$ARCH" in
        x86_64|aarch64|arm64) ;;
        *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
    esac

    TAG="${ATELIER_RELEASE_TAG:-latest}"

    # If TAG is "latest", resolve the actual version tag from GitHub API
    if [[ "$TAG" == "latest" ]]; then
        REAL_TAG=$(curl -sI https://github.com/atelier-ws/atelier/releases/latest | grep -i location | awk -F/ '{print $NF}' | tr -d '\r')
        if [[ -z "$REAL_TAG" ]]; then
            echo "Failed to resolve 'latest' tag. Falling back to cached 'latest' if available." >&2
        else
            TAG="$REAL_TAG"
        fi
    fi

    SUFFIX="${OS}-${ARCH}"
    ASSET="atelier-distribution-${SUFFIX}.tar.gz"
    URL="https://github.com/atelier-ws/atelier/releases/download/${TAG}/${ASSET}"

    CACHE_DIR="${CACHE_ROOT}/${TAG}/${SUFFIX}"
    VENV="${CACHE_DIR}/venv"
    ATELIER_BIN="${VENV}/bin/atelier"

    if [[ "${CACHE_ENABLED}" != "1" || ! -x "$ATELIER_BIN" ]]; then
        TMP_BASE="/tmp/atelier-session-${SUFFIX}-$$"
        ARCHIVE="${TMP_BASE}.tar.gz"
        cleanup() { rm -rf "${TMP_BASE}" "${ARCHIVE}" 2>/dev/null || true; }
        trap cleanup EXIT

        mkdir -p "${TMP_BASE}"
        if command -v curl >/dev/null 2>&1; then
            curl -fL --retry 3 --retry-delay 2 --connect-timeout 15 "${URL}" -o "${ARCHIVE}"
        elif command -v wget >/dev/null 2>&1; then
            wget -qO "${ARCHIVE}" "${URL}"
        else
            echo "Missing downloader: install curl or wget." >&2
            exit 1
        fi

        verify_checksum "${ARCHIVE}" "${URL}"

        tar -xzf "${ARCHIVE}" -C "${TMP_BASE}"
        WHEEL="$(ls "${TMP_BASE}"/bin/atelier-*.whl 2>/dev/null | head -1 || true)"
        if [[ -z "$WHEEL" ]]; then
            echo "atelier wheel not found in release archive ${ASSET}" >&2
            exit 1
        fi
        CONSTRAINTS=""
        [[ -f "${TMP_BASE}/constraints.txt" ]] && CONSTRAINTS="${TMP_BASE}/constraints.txt"

        rm -rf "$VENV"
        mkdir -p "$CACHE_DIR"
        install_wheel_to_venv "$WHEEL" "$VENV" "$CONSTRAINTS"
    fi
fi

if [[ ! -x "$ATELIER_BIN" ]]; then
    echo "atelier not found after install: ${ATELIER_BIN}" >&2
    exit 1
fi

if "${ATELIER_BIN}" session hosts --help >/dev/null 2>&1; then
    # Default to direct host scanning unless caller already selected --source.
    HAS_SOURCE=0
    for arg in "$@"; do
        if [[ "$arg" == "--source" || "$arg" == --source=* ]]; then
            HAS_SOURCE=1
            break
        fi
    done
    if [[ "$HAS_SOURCE" == "1" ]]; then
        exec "${ATELIER_BIN}" session hosts "$@"
    fi
    exec "${ATELIER_BIN}" session hosts --source live "$@"
fi

echo "The downloaded Atelier release does not include 'session hosts' yet." >&2
echo "Use a newer ATELIER_RELEASE_TAG." >&2
exit 2
