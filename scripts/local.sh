#!/usr/bin/env bash
# local.sh — Install Atelier from a local repository checkout.
#
# Usage (from repo root):
#   bash scripts/local.sh
#   bash scripts/local.sh --dry-run
#
# This script installs the Python package via uv, then runs the shared
# setup (code tools, host integrations, services). For binary-only
# installs see scripts/bundle.sh.
#
# All shared configuration, logging, prompts, and the run_setup()
# orchestrator live in scripts/lib/common.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

# Caller-specific mode flags. ATELIER_BINARY_MODE is retained for
# compatibility but unused in source mode; ATELIER_LOCAL marks this as a
# source-checkout install so run_setup wires host configs into the repo.
ATELIER_BINARY_MODE="${ATELIER_BINARY_MODE:-0}"
ATELIER_LOCAL=1

# ---- source-only: Python package install ------------------------------------
install_uv_if_needed() {
    if command -v uv >/dev/null 2>&1; then
        verbose "Found uv: $(uv --version 2>/dev/null || echo unknown)"
        return
    fi

    need_cmd curl
    verbose "Installing uv (official installer)..."
    if [[ "$ATELIER_DRY_RUN" == "1" ]]; then
        echo "[dry-run] curl -LsSf https://astral.sh/uv/install.sh | sh"
    else
        # shellcheck disable=SC2016
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi

    if [[ -x "${HOME}/.local/bin/uv" ]]; then
        export PATH="${HOME}/.local/bin:${PATH}"
    fi

    command -v uv >/dev/null 2>&1 || fail "uv install completed but uv is still not on PATH"
    verbose "Installed uv: $(uv --version 2>/dev/null || echo unknown)"
}

install_console_scripts() {
    local extras="mcp,memory,smart,cloud,postgres,vector,parsers,rename"
    local package_spec="${ATELIER_INSTALL_DIR}[${extras}]"

    if [[ "$ATELIER_DRY_RUN" == "1" ]]; then
        stop_existing_atelier_processes
        printf '[dry-run] uv tool uninstall atelier (if present)\n'
        printf '[dry-run] UV_TOOL_BIN_DIR=%q UV_TOOL_DIR=%q uv tool install' "$ATELIER_BIN_DIR" "$ATELIER_TOOL_DIR"
        printf ' %q' "$package_spec"
        printf '\n'
        return
    fi

    mkdir -p "$ATELIER_BIN_DIR" "$ATELIER_TOOL_DIR"
    stop_existing_atelier_processes
    
    # Forcefully remove any existing manual wrappers to prevent uv collision
    rm -f "${ATELIER_BIN_DIR}/atelier"

    # Gracefully remove old installation first
    UV_TOOL_BIN_DIR="$ATELIER_BIN_DIR" \
        UV_TOOL_DIR="$ATELIER_TOOL_DIR" \
        uv tool uninstall atelier >/dev/null 2>&1 || true
    
    UV_TOOL_BIN_DIR="$ATELIER_BIN_DIR" \
        UV_TOOL_DIR="$ATELIER_TOOL_DIR" \
        uv tool install "$package_spec" --force

}

stop_existing_atelier_processes() {
    [[ "$ATELIER_INSTALL_CLEAN_PROCESSES" == "1" ]] || return 0

    local current_pid="$$"
    local parent_pid="${PPID:-}"
    local pids=()
    local pid args

    local ps_out
    ps_out="$(mktemp "${TMPDIR:-/tmp}/atelier-ps.XXXXXX")"
    ps -eo pid=,args= 2>/dev/null > "$ps_out" || true
    while read -r pid args; do
        [[ -n "${pid:-}" && -n "${args:-}" ]] || continue
        [[ "$pid" == "$current_pid" || "$pid" == "$parent_pid" ]] && continue

        case "$args" in
            *"atelier mcp --host"*|\
            *"/atelier mcp "*|\
            *" atelier mcp "*|\
            *"/atelier --root "*servicectl*|\
            *" atelier --root "*servicectl*|\
            *"/atelier servicectl "*|\
            *" atelier servicectl "*|\
            *"/atelier stack run"*|\
            *" atelier stack run"*)
                pids+=("$pid")
                ;;
        esac
    done < "$ps_out"
    rm -f "$ps_out"

    [[ ${#pids[@]} -gt 0 ]] || return 0

    if [[ "$ATELIER_DRY_RUN" == "1" ]]; then
        printf '[dry-run] stop stale Atelier processes: %s\n' "${pids[*]}"
        return 0
    fi

    verbose "Stopping stale Atelier processes before reinstall: ${pids[*]}"
    kill -TERM "${pids[@]}" 2>/dev/null || true
    sleep 1
    local alive=()
    for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            alive+=("$pid")
        fi
    done
    if [[ ${#alive[@]} -gt 0 ]]; then
        kill -KILL "${alive[@]}" 2>/dev/null || true
    fi
}

persist_install_record() {
    local record_dir
    record_dir="$(dirname "$ATELIER_INSTALL_RECORD")"

    if [[ "$ATELIER_DRY_RUN" == "1" ]]; then
        echo "[dry-run] mkdir -p $record_dir"
        echo "[dry-run] printf '%s\\n' '$ATELIER_INSTALL_DIR' > '$ATELIER_INSTALL_RECORD'"
        return
    fi

    mkdir -p "$record_dir"
    printf '%s\n' "$ATELIER_INSTALL_DIR" > "$ATELIER_INSTALL_RECORD"
}

# ---- arg parsing (source-specific flags) ------------------------------------
# Parse flags relevant to source install (--local/--remote are no-ops here,
# everything else is forwarded to common vars already declared in common.sh).
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
        --local|--remote|--no-local) : ;;  # no-op, always source mode
        *) : ;;
    esac
    shift
done

# ---- main -------------------------------------------------------------------
main() {
    need_cmd git
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

    install_uv_if_needed
    install_node_if_needed

    ATELIER_INSTALL_DIR="$(pwd)"
    export ATELIER_INSTALL_DIR

    step_start "Installing Atelier"
    if [[ "$ATELIER_DRY_RUN" == "1" ]]; then
        install_console_scripts
    else
        spin_tail "Installing packages" install_console_scripts
    fi
    persist_install_record
    step_done

    run_setup
}

main "$@"
