#!/usr/bin/env bash
# sessions.sh — download Atelier distribution to /tmp and run `atelier session hosts`.
#
# Examples:
#   bash scripts/sessions.sh
#   bash scripts/sessions.sh --host codex --limit 10
#   bash scripts/sessions.sh --host copilot --id d6cf6de0 --verbose
#   bash scripts/sessions.sh --local                    # use local bundle/bin/atelier (no download)
#   bash scripts/sessions.sh --local --host copilot     # local binary + extra flags
#
# Optional env:
#   ATELIER_RELEASE_TAG=v1.2.3        (default: latest)
#   ATELIER_SESSION_CACHE=1            (default: 1; cache binary under /tmp)
#   ATELIER_SESSION_CACHE_DIR=/tmp/atelier-session-cache
#   ATELIER_LOCAL_BIN=./bundle/bin/atelier  (override local binary path)

set -euo pipefail

# ── Parse --local flag out before forwarding remaining args ──────────────────
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

if [[ "$USE_LOCAL" == "1" ]]; then
    # Resolve the local binary: prefer explicit ATELIER_LOCAL_BIN env, then
    # look for bundle/bin/atelier relative to script location, then cwd.
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    LOCAL_BIN="${ATELIER_LOCAL_BIN:-}"
    if [[ -z "$LOCAL_BIN" ]]; then
        # Try next to the script (dist layout: scripts/ sibling of bin/)
        if [[ -x "${SCRIPT_DIR}/../bin/atelier" ]]; then
            LOCAL_BIN="$(cd "${SCRIPT_DIR}/../bin" && pwd)/atelier"
        # Try repo root bundle/bin/
        elif [[ -x "${SCRIPT_DIR}/../bundle/bin/atelier" ]]; then
            LOCAL_BIN="$(cd "${SCRIPT_DIR}/../bundle/bin" && pwd)/atelier"
        # Try cwd-relative bundle/bin/
        elif [[ -x "./bundle/bin/atelier" ]]; then
            LOCAL_BIN="$(pwd)/bundle/bin/atelier"
        else
            echo "--local: could not find local atelier binary." >&2
            echo "  Tried: ${SCRIPT_DIR}/../bin/atelier, ${SCRIPT_DIR}/../bundle/bin/atelier, ./bundle/bin/atelier" >&2
            echo "  Set ATELIER_LOCAL_BIN=/path/to/atelier to override." >&2
            exit 1
        fi
    fi
    if [[ ! -x "$LOCAL_BIN" ]]; then
        echo "--local: binary not executable: $LOCAL_BIN" >&2
        exit 1
    fi
    echo "◆ Using local binary: $LOCAL_BIN" >&2
    ATELIER_BIN="$LOCAL_BIN"

    # Skip download / cache logic; fall through to exec below.
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
    ASSET="atelier-binaries-${SUFFIX}.tar.gz"
    URL="https://github.com/atelier-ws/atelier/releases/download/${TAG}/${ASSET}"

    TMP_BASE="/tmp/atelier-session-${SUFFIX}-$$"
    BIN_DIR="${TMP_BASE}/bin"
    ARCHIVE="${TMP_BASE}.tar.gz"
    CACHE_ENABLED="${ATELIER_SESSION_CACHE:-1}"
    CACHE_ROOT="${ATELIER_SESSION_CACHE_DIR:-/tmp/atelier-session-cache}"
    CACHE_DIR="${CACHE_ROOT}/${TAG}/${SUFFIX}"
    CACHED_BIN="${CACHE_DIR}/bin/atelier"

    cleanup() {
        rm -rf "${TMP_BASE}" "${ARCHIVE}" 2>/dev/null || true
    }
    trap cleanup EXIT

    ATELIER_BIN="${CACHED_BIN}"
    if [[ ! -x "${ATELIER_BIN}" ]]; then
        mkdir -p "${TMP_BASE}"
        if command -v curl >/dev/null 2>&1; then
            curl -fL --retry 3 --retry-delay 2 --connect-timeout 15 "${URL}" -o "${ARCHIVE}"
        elif command -v wget >/dev/null 2>&1; then
            wget -qO "${ARCHIVE}" "${URL}"
        else
            echo "Missing downloader: install curl or wget." >&2
            exit 1
        fi

        tar -xzf "${ARCHIVE}" -C "${TMP_BASE}"
        ATELIER_BIN="${BIN_DIR}/atelier"
        if [[ ! -x "${ATELIER_BIN}" ]]; then
            echo "atelier binary not found after extraction: ${ATELIER_BIN}" >&2
            exit 1
        fi

        if [[ "${CACHE_ENABLED}" == "1" ]]; then
            mkdir -p "${CACHE_DIR}"
            rm -rf "${CACHE_DIR}/bin"
            cp -a "${BIN_DIR}" "${CACHE_DIR}/"
            ATELIER_BIN="${CACHED_BIN}"
        fi
    fi
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
