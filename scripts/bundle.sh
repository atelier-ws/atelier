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

# A binary install is never a source checkout; keep host configs global
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

# ---- main -------------------------------------------------------------------
main() {
    need_cmd bash

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
