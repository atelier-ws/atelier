#!/usr/bin/env bash
# sessions.sh — download Atelier distribution to /tmp and run `atelier session hosts`.
#
# Examples:
#   bash scripts/sessions.sh
#   bash scripts/sessions.sh --host codex --limit 10
#   bash scripts/sessions.sh --host copilot --id d6cf6de0 --verbose
#
# Optional env:
#   ATELIER_RELEASE_TAG=v1.2.3  (default: latest)
#   ATELIER_SESSION_CACHE=1      (default: 1; cache binary under /tmp)
#   ATELIER_SESSION_CACHE_DIR=/tmp/atelier-session-cache

set -euo pipefail

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
SUFFIX="${OS}-${ARCH}"
ASSET="atelier-binaries-${SUFFIX}.tar.gz"
if [[ "$TAG" == "latest" ]]; then
    URL="https://github.com/atelier-runtime/atelier/releases/latest/download/${ASSET}"
else
    URL="https://github.com/atelier-runtime/atelier/releases/download/${TAG}/${ASSET}"
fi

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

# Fallback for unreleased binaries: if this script is run inside a source checkout,
# use the local CLI so new commands can be tested before a release is cut.
if command -v uv >/dev/null 2>&1 && [[ -f "pyproject.toml" ]]; then
    HAS_SOURCE=0
    for arg in "$@"; do
        if [[ "$arg" == "--source" || "$arg" == --source=* ]]; then
            HAS_SOURCE=1
            break
        fi
    done
    if [[ "$HAS_SOURCE" == "1" ]]; then
        exec uv run --project . atelier session hosts "$@"
    fi
    exec uv run --project . atelier session hosts --source live "$@"
fi

echo "The downloaded Atelier release does not include 'session hosts' yet." >&2
echo "Use a newer ATELIER_RELEASE_TAG, or run from source with: uv run atelier session hosts ..." >&2
exit 2
