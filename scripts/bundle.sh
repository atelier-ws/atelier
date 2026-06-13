#!/usr/bin/env bash
# bundle.sh — Post-extract setup for a pre-built Atelier binary.
#
# Called by install.sh after the binary tarball has been extracted.
# ATELIER_INSTALL_DIR and ATELIER_BIN_DIR must already be set, and the
# Atelier binary must already exist at "$ATELIER_BIN_DIR/atelier".
#
# Can also be called directly to re-run setup after a manual binary update:
#   ATELIER_INSTALL_DIR=~/.local ATELIER_BIN_DIR=~/.local/bin bash ~/.local/scripts/bundle.sh
#
# All shared configuration, logging, prompts, and the run_setup()
# orchestrator live in scripts/lib/common.sh. For source-checkout installs
# (uv tool install) see scripts/local.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

# A distribution install is never a source checkout; keep host configs global
# unless an explicit --workspace is provided.
ATELIER_LOCAL=0

# ---- arg parsing ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) ATELIER_DRY_RUN=1 ;;
        --no-hosts) ATELIER_NO_HOSTS=1 ;;
        --no-servicectl) ATELIER_NO_SERVICECTL=1 ;;
        --no-stack) ATELIER_NO_STACK=1 ;;
        --verbose|-v) ATELIER_VERBOSE=1 ;;
        --non-interactive) ATELIER_NON_INTERACTIVE=1 ;;
        --advanced) ATELIER_ADVANCED=1 ;;
        --memory) ATELIER_MEMORY_BACKEND="${2:-}"; shift ;;
        --memory=*) ATELIER_MEMORY_BACKEND="${1#--memory=}" ;;
        --zoekt) ATELIER_ZOEKT=1 ;;
        --workspace) HOST_SCOPE_ARGS+=(--workspace "${2:-}"); shift ;;
        --workspace=*) HOST_SCOPE_ARGS+=(--workspace "${1#--workspace=}") ;;
        --all) HOST_FLAGS+=(--all) ;;
        *) : ;;
    esac
    shift
done

# ---- install atelier from bundled wheel ------------------------------------
install_atelier_from_wheel() {
    local wheel
    wheel="$(find "${ATELIER_BIN_DIR:-${ATELIER_INSTALL_DIR}/bin}" -maxdepth 1 -name "*.whl" 2>/dev/null | head -1)"
    if [[ -z "${wheel}" ]]; then
        info "No bundled wheel found — assuming atelier already installed"
        return 0
    fi

    if ! command -v uv >/dev/null 2>&1; then
        info "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="${HOME}/.local/bin:${PATH}"
    fi

    # Pin every transitive dependency to its locked version via the constraints
    # file build.sh ships next to this script (<bundle>/constraints.txt). Without
    # it, `uv tool install` ignores uv.lock and resolves the wheel's unbounded
    # `>=` deps from scratch against PyPI (~293 packages) — the "stuck resolving
    # packages" hang on a cold machine. With `-c`, resolution is deterministic
    # and does no version search. This is the single install step shared by both
    # `make prod` and the distribution installer: install.sh only downloads and
    # extracts the bundle, then runs this exact script the same way.
    local constraints_arg=()
    if [[ -f "${SCRIPT_DIR}/../constraints.txt" ]]; then
        info "Using bundled dependency constraints"
        constraints_arg=(-c "${SCRIPT_DIR}/../constraints.txt")
    fi

    local extras="mcp,memory,smart,cloud,postgres,vector,parsers,rename"
    info "Installing atelier from wheel (uv tool install)..."
    uv tool install "${wheel}[${extras}]" ${constraints_arg[@]+"${constraints_arg[@]}"} --reinstall-package atelier

    # Re-derive ATELIER_BIN_DIR to the uv tool install location so that
    # run_setup() finds the real atelier binary (not the wheel-only
    # staging dir). uv tool install puts binaries in
    # ~/.local/bin (or UV_TOOL_BIN_DIR if set).
    local uv_bin_dir
    uv_bin_dir="$(uv tool dir --bin 2>/dev/null || echo "${HOME}/.local/bin")"
    if [[ -x "${uv_bin_dir}/atelier" ]]; then
        ATELIER_BIN_DIR="${uv_bin_dir}"
        export ATELIER_BIN_DIR
        info "atelier installed: $(atelier --version 2>/dev/null || echo unknown)"
    else
        info "atelier installed (binary not found in uv tool dir; using PATH fallback)"
    fi
}

# ---- main -------------------------------------------------------------------
main() {
    need_cmd bash

    install_atelier_from_wheel

    print_installer_header
    host_wizard
    prompt_memory_selection
    prompt_auto_optimize_selection
    prompt_local_zoekt_selection

    if supports_interactive_selector; then
        print_installer_footer
    fi

    case "$ATELIER_MEMORY_BACKEND" in
        letta|openmemory|"") ;;
        *) fail "--memory must be 'letta' or 'openmemory', got: '$ATELIER_MEMORY_BACKEND'" ;;
    esac
    [[ -n "$ATELIER_MEMORY_BACKEND" ]] && ATELIER_ADVANCED=1

    install_node_if_needed

    run_setup
}

main "$@"
