#!/usr/bin/env bash
# install_codex.sh — Install Atelier into Codex CLI
#
# What it does:
#   Global mode: installs a personal Codex marketplace, plugin bundle, and agents.
#   Workspace mode (--workspace DIR): installs repo-local plugin artifacts and agents.
#
# Options:
#   --dry-run        Print what would happen, touch nothing
#   --print-only     Print manual install steps, touch nothing
#   --workspace DIR  Install project-local artifacts into DIR
#   --strict         Exit nonzero if 'codex' CLI is not on PATH

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
source "${SCRIPT_DIR}/lib/managed_context.sh"

PLUGIN_TEMPLATE="${ATELIER_REPO}/integrations/codex/plugin"
SKILL_BUILDER="${SCRIPT_DIR}/build_host_skills.sh"
STAGING_DIR="${HOME}/.atelier/codex-plugin"
USER_CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"

DRY_RUN=false
PRINT_ONLY=false
STRICT=false
WORKSPACE=""
WORKSPACE_SET=false
PLUGIN_INSTALL_PENDING=false
MARKETPLACE_NAME="atelier-local"
PLUGIN_ID="atelier@atelier-local"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=true ;;
        --print-only) PRINT_ONLY=true ;;
        --strict)     STRICT=true ;;
        --workspace)
            if [ $# -lt 2 ]; then
                echo "Missing value for --workspace" >&2
                exit 1
            fi
            WORKSPACE="$2"
            WORKSPACE_SET=true
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
    shift
done

if $WORKSPACE_SET; then
    WORKSPACE="$(cd "$WORKSPACE" && pwd)"
    INSTALL_SCOPE="workspace"
    CODEX_DIR="${WORKSPACE}/.codex"
    PLUGIN_DIR="${CODEX_DIR}/plugins/atelier"
    AGENTS_DIR="${CODEX_DIR}/agents"
    AGENTS_FILE="${WORKSPACE}/AGENTS.md"
    TASKS_DEST_DIR="${CODEX_DIR}/tasks"
    CODEX_CONFIG="${CODEX_DIR}/config.toml"
    MARKETPLACE_ROOT="$WORKSPACE"
else
    INSTALL_SCOPE="global"
    CODEX_DIR="$USER_CODEX_HOME"
    PLUGIN_DIR="${CODEX_DIR}/plugins/atelier"
    AGENTS_DIR="${CODEX_DIR}/agents"
    AGENTS_FILE="${CODEX_DIR}/AGENTS.md"
    TASKS_DEST_DIR=""
    CODEX_CONFIG="${CODEX_DIR}/config.toml"
    MARKETPLACE_ROOT="$HOME"
fi

PLUGIN_MCP_JSON="${PLUGIN_DIR}/.mcp.json"
CODEX_MARKETPLACE="${MARKETPLACE_ROOT}/.agents/plugins/marketplace.json"
USER_CODEX_CONFIG="${USER_CODEX_HOME}/config.toml"

info()  { [[ "${ATELIER_VERBOSE:-0}" == "1" ]] && echo "[atelier:codex] $*" || true; }
warn()  { echo "[atelier:codex] WARN: $*" >&2; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }

print_manual_steps() {
    echo ""
    echo "=== Atelier Codex — Manual Install Steps ==="
    echo "Scope: ${INSTALL_SCOPE}"
    echo ""
    echo "1. Copy the Atelier plugin source:"
    echo "   mkdir -p '${PLUGIN_DIR}'"
    echo "   cp -R '${ATELIER_REPO}/integrations/codex/plugin/.' '${PLUGIN_DIR}/'"
    echo "   cp -R '${ATELIER_REPO}/integrations/codex/hooks' '${PLUGIN_DIR}/'"
    echo "   cp -R '${ATELIER_REPO}/integrations/codex/plugin/agents' '${PLUGIN_DIR}/'"
    echo "   cp '${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md' '${PLUGIN_DIR}/agents/atelier.md'"
    echo "   bash '${SKILL_BUILDER}' --host codex --dest '${PLUGIN_DIR}/skills'"
    echo ""
    echo "2. Add Atelier to '${CODEX_MARKETPLACE}' with:"
    echo "   source.path = './.codex/plugins/atelier'"
    echo "   policy.installation = 'INSTALLED_BY_DEFAULT'"
    echo ""
    echo "3. Install the seven custom agents under '${AGENTS_DIR}'."
    echo ""
    echo "4. Restart Codex. Open /plugins to confirm '${PLUGIN_ID}' is enabled."
    echo "   Custom agents are spawned by name and appear in /agent after spawning."
}

# Print-only must be completely side-effect free and must not require Codex.
if $PRINT_ONLY; then
    print_manual_steps
    exit 0
fi

# Check the CLI before staging anything. A missing optional host must not leave
# artifacts behind. Dry-run is allowed to continue so it can still show a plan.
if ! command -v codex &>/dev/null; then
    if $STRICT; then
        echo "[atelier:codex] ERROR: 'codex' CLI not found. Install from https://github.com/openai/codex" >&2
        exit 1
    fi
    if $DRY_RUN; then
        warn "'codex' CLI not found — continuing dry-run without invoking Codex"
    else
        warn "'codex' CLI not found — SKIPPING. Install from https://github.com/openai/codex"
        echo "=== SKIPPED (codex CLI absent) ==="
        exit 0
    fi
else
    info "Found Codex: $(codex --version 2>/dev/null || echo 'version unknown')"
fi

# In workspace mode, Codex must run from the workspace so it discovers the repo
# marketplace and project config. Do not redefine CODEX_HOME: plugin enabled
# state and cache remain user-scoped under ~/.codex (or the caller's CODEX_HOME).
codex_cmd() {
    if $WORKSPACE_SET; then
        (cd "$WORKSPACE" && codex "$@")
    else
        codex "$@"
    fi
}

resolve_real_path() {
    python3 - "$1" <<'PYEOF'
import os
import sys

print(os.path.realpath(sys.argv[1]))
PYEOF
}

resolve_atelier_runtime_python() {
    local atelier_launcher atelier_python
    atelier_launcher="$(command -v atelier || true)"
    if [ -z "$atelier_launcher" ]; then
        echo "[atelier:codex] ERROR: cannot resolve Atelier Python interpreter: 'atelier' is not on PATH" >&2
        exit 1
    fi

    if [[ "${ATELIER_BINARY_MODE:-0}" == "1" ]]; then
        printf '%s\n' "python3"
        return
    fi

    atelier_launcher="$(resolve_real_path "$atelier_launcher")"
    atelier_python="$(head -n 1 "$atelier_launcher")"
    atelier_python="${atelier_python#\#!}"
    if [[ "$atelier_python" != /* ]] || [ ! -x "$atelier_python" ]; then
        echo "[atelier:codex] ERROR: cannot resolve Atelier Python interpreter from $atelier_launcher" >&2
        exit 1
    fi
    printf '%s\n' "$atelier_python"
}

resolve_atelier_hook_python() {
    local atelier_launcher
    if [[ "${ATELIER_BINARY_MODE:-0}" == "1" ]]; then
        atelier_launcher="$(command -v atelier || true)"
        if [ -z "$atelier_launcher" ]; then
            echo "[atelier:codex] ERROR: cannot resolve Atelier launcher: 'atelier' is not on PATH" >&2
            exit 1
        fi
        resolve_real_path "$atelier_launcher"
        return
    fi
    resolve_atelier_runtime_python
}

stage_plugin_bundle() {
    # Recreate staging from scratch so removed files cannot survive upgrades.
    run "rm -rf $(printf %q "$STAGING_DIR")"
    run "mkdir -p $(printf %q "$STAGING_DIR/.codex-plugin")"
    run "cp $(printf %q "${PLUGIN_TEMPLATE}/.codex-plugin/plugin.json") $(printf %q "$STAGING_DIR/.codex-plugin/")"
    run "cp $(printf %q "${PLUGIN_TEMPLATE}/.mcp.json") $(printf %q "$STAGING_DIR/")"
    run "cp -R $(printf %q "${ATELIER_REPO}/integrations/codex/hooks") $(printf %q "$STAGING_DIR/")"
    run "cp -R $(printf %q "${ATELIER_REPO}/integrations/codex/plugin/scripts") $(printf %q "$STAGING_DIR/")"
    run "cp -R $(printf %q "${ATELIER_REPO}/integrations/codex/plugin/agents") $(printf %q "$STAGING_DIR/")"
    run "mkdir -p $(printf %q "$STAGING_DIR/agents")"
    run "cp $(printf %q "${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md") $(printf %q "$STAGING_DIR/agents/atelier.md")"
    run "bash $(printf %q "$SKILL_BUILDER") --host codex --dest $(printf %q "$STAGING_DIR/skills")"
    PLUGIN_TEMPLATE="$STAGING_DIR"
}

backup_file() {
    local path="$1"
    if $WORKSPACE_SET; then
        return
    fi
    if [ -f "$path" ]; then
        local backup="${path}.atelier-backup.$(date +%Y%m%dT%H%M%S)"
        run "cp $(printf %q "$path") $(printf %q "$backup")"
        info "backed up $path → $backup"
    fi
}

backup_path() {
    local path="$1"
    if $WORKSPACE_SET; then
        return
    fi
    if [ -e "$path" ]; then
        local backup="${path}.atelier-backup.$(date +%Y%m%dT%H%M%S)"
        if [ -d "$path" ]; then
            run "cp -R $(printf %q "$path") $(printf %q "$backup")"
        else
            run "cp $(printf %q "$path") $(printf %q "$backup")"
        fi
        info "backed up $path → $backup"
    fi
}

merge_agents_file() {
    local source_file="$1"
    local dest_file="$2"

    if [ ! -f "$dest_file" ]; then
        if $DRY_RUN; then
            atelier_write_managed_copy "$source_file" "$dest_file" "true"
        else
            atelier_write_managed_copy "$source_file" "$dest_file" "false"
        fi
        info "created $dest_file"
        return
    fi

    backup_file "$dest_file"
    atelier_upsert_managed_block "$source_file" "$dest_file" "$DRY_RUN"
    info "merged Atelier Codex instructions into $dest_file"
}

install_plugin_bundle() {
    if [ -e "$PLUGIN_DIR" ]; then
        backup_path "$PLUGIN_DIR"
        run "rm -rf $(printf %q "$PLUGIN_DIR")"
    fi
    run "mkdir -p $(printf %q "$PLUGIN_DIR")"
    run "cp -R $(printf %q "$PLUGIN_TEMPLATE/.") $(printf %q "$PLUGIN_DIR/")"
}

patch_plugin_hooks() {
    if $DRY_RUN; then
        echo "  [dry-run] patch ${PLUGIN_DIR}/hooks/hooks.json with absolute Atelier runtime paths"
        return
    fi

    local atelier_python
    atelier_python="$(resolve_atelier_hook_python)"
    if [[ "$atelier_python" != /* ]] || [ ! -x "$atelier_python" ]; then
        echo "[atelier:codex] ERROR: cannot resolve Atelier hook runtime from $atelier_python" >&2
        exit 1
    fi

    HOOKS_PATH="${PLUGIN_DIR}/hooks/hooks.json" \
    ATELIER_PYTHON="$atelier_python" \
    ATELIER_REPO_SRC="${ATELIER_REPO}/src" \
    python3 - <<'PYEOF'
import json
import os
from pathlib import Path

path = Path(os.environ["HOOKS_PATH"])
data = json.loads(path.read_text(encoding="utf-8"))
for groups in data.get("hooks", {}).values():
    for group in groups:
        for hook in group.get("hooks", []):
            command = hook.get("command")
            if isinstance(command, str):
                hook["command"] = command.replace(
                    "__ATELIER_PYTHON__", os.environ["ATELIER_PYTHON"]
                ).replace("__ATELIER_REPO_SRC__", os.environ["ATELIER_REPO_SRC"])
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PYEOF
}

patch_plugin_mcp() {
    if $DRY_RUN; then
        echo "  [dry-run] patch $PLUGIN_MCP_JSON to run atelier mcp --host codex"
        return
    fi

    PLUGIN_MCP_JSON_PATH="$PLUGIN_MCP_JSON" \
    ATELIER_WORKSPACE_MODE="$($WORKSPACE_SET && printf 1 || printf 0)" \
    ATELIER_WORKSPACE_VALUE="$WORKSPACE" \
    python3 - <<'PYEOF'
import json
import os
from pathlib import Path

path = Path(os.environ["PLUGIN_MCP_JSON_PATH"])
data = json.loads(path.read_text(encoding="utf-8"))
server = data.setdefault("atelier", {})
server["command"] = "atelier"
server["args"] = ["mcp", "--host", "codex"]
env = dict(server.get("env") or {})
if os.environ["ATELIER_WORKSPACE_MODE"] == "1":
    env["ATELIER_WORKSPACE_ROOT"] = os.environ["ATELIER_WORKSPACE_VALUE"]
else:
    env.pop("ATELIER_WORKSPACE_ROOT", None)
server["env"] = env
# Older Atelier bundles emitted alwaysLoad/cwd, which are not part of the
# documented Codex plugin MCP schema.
server.pop("alwaysLoad", None)
server.pop("cwd", None)
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PYEOF
}

cleanup_legacy_codex_config() {
    local config_path="$1"
    if $DRY_RUN; then
        echo "  [dry-run] remove obsolete Atelier per-agent registration block from ${config_path}"
        return
    fi
    if [ ! -f "$config_path" ]; then
        return
    fi

    CODEX_CONFIG_PATH="$config_path" python3 - <<'PYEOF'
import os
import re
from pathlib import Path

path = Path(os.environ["CODEX_CONFIG_PATH"])
text = path.read_text(encoding="utf-8")
original = text

# Current Codex discovers standalone custom agent files directly from
# .codex/agents or ~/.codex/agents. Remove the old generated registration block.
text = re.sub(
    r"(?ms)^# ATELIER:CODEX AGENTS START\n.*?^# ATELIER:CODEX AGENTS END\n?",
    "",
    text,
)

# A previous installer could leave tool-only MCP tables after MCP registration
# failed. Remove those orphan tables only when no direct Atelier MCP server is
# configured. Plugin-scoped MCP policy belongs under [plugins.<id>.mcp_servers].
if not re.search(r"(?m)^\[mcp_servers\.atelier\]\s*$", text):
    tools = (
        "shell", "read", "grep", "edit", "callees", "codemod",
        "memory", "callers", "explore", "web_fetch", "search", "usages",
    )
    for tool in tools:
        text = re.sub(
            rf"(?ms)^\[mcp_servers\.atelier\.tools\.{re.escape(tool)}\]\s*\n"
            rf"(?:(?!^\[).*(?:\n|$))*",
            "",
            text,
        )

text = re.sub(r"\n{3,}", "\n\n", text).strip()
if text:
    text += "\n"
if text != original:
    path.write_text(text, encoding="utf-8")
    print(f"[atelier:codex] removed obsolete Atelier config entries from {path}")
PYEOF
}

write_marketplace() {
    if $DRY_RUN; then
        echo "  [dry-run] register Atelier in ${CODEX_MARKETPLACE} with INSTALLED_BY_DEFAULT"
        return
    fi

    mkdir -p "$(dirname "$CODEX_MARKETPLACE")"
    MARKETPLACE_PATH="$CODEX_MARKETPLACE" python3 - <<'PYEOF'
import json
import os
from pathlib import Path

path = Path(os.environ["MARKETPLACE_PATH"])
if path.exists():
    data = json.loads(path.read_text(encoding="utf-8"))
else:
    data = {"name": "atelier-local", "plugins": []}

name = data.get("name")
if not isinstance(name, str) or not name.strip():
    name = "atelier-local"
    data["name"] = name

data.setdefault("interface", {"displayName": "Atelier local"})
entry = {
    "name": "atelier",
    "source": {"source": "local", "path": "./.codex/plugins/atelier"},
    "policy": {"installation": "INSTALLED_BY_DEFAULT", "authentication": "ON_INSTALL"},
    "category": "Coding",
}
plugins = [p for p in data.get("plugins", []) if isinstance(p, dict) and p.get("name") != "atelier"]
data["plugins"] = plugins + [entry]
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(name)
PYEOF
}

install_codex_plugin() {
    if $DRY_RUN; then
        echo "  [dry-run] attempt to install ${PLUGIN_ID}; otherwise restart Codex and use /plugins"
        return
    fi

    # The marketplace policy makes the plugin available after restart. Try the
    # non-interactive command when the installed Codex build supports it, but do
    # not fail a valid agent/plugin projection when activation is restart-bound.
    codex_cmd plugin remove "atelier@openai-curated" >/dev/null 2>&1 || true
    if codex_cmd plugin add "$PLUGIN_ID" >/dev/null 2>&1; then
        info "installed Codex plugin ${PLUGIN_ID}"
        return
    fi
    if codex_cmd plugin install "$PLUGIN_ID" >/dev/null 2>&1; then
        info "installed Codex plugin ${PLUGIN_ID}"
        return
    fi

    PLUGIN_INSTALL_PENDING=true
    warn "Codex did not activate ${PLUGIN_ID} non-interactively; restart Codex, open /plugins, and enable Atelier."
}

project_custom_agents() {
    cleanup_legacy_codex_config "$CODEX_CONFIG"

    if $DRY_RUN; then
        echo "  [dry-run] project seven custom agents into '${AGENTS_DIR}'"
        return
    fi

    local atelier_python
    atelier_python="$(resolve_atelier_runtime_python)"
    ATELIER_AGENTS_DIR_VALUE="$AGENTS_DIR" \
    ATELIER_WORKSPACE_VALUE="$WORKSPACE" \
    ATELIER_REPO_VALUE="$ATELIER_REPO" \
    ATELIER_WORKSPACE_MODE="$($WORKSPACE_SET && printf 1 || printf 0)" \
    PYTHONPATH="${ATELIER_REPO}/src${PYTHONPATH:+:${PYTHONPATH}}" \
    "$atelier_python" - <<'PYEOF'
import os
from pathlib import Path
from atelier.core.capabilities.workspace_host_overrides import write_codex_agents

agents_dir = Path(os.environ["ATELIER_AGENTS_DIR_VALUE"])
repo_root = Path(os.environ["ATELIER_REPO_VALUE"])
workspace = Path(os.environ["ATELIER_WORKSPACE_VALUE"]) if os.environ["ATELIER_WORKSPACE_MODE"] == "1" else None
written = write_codex_agents(agents_dir, model_workspace=workspace, repo_root=repo_root)
print(f"[atelier:codex] projected {len(written)} custom Codex agents into {agents_dir}")
PYEOF
}

# ---- stage + install plugin bundle -------------------------------------------
stage_plugin_bundle
info "Installing Codex plugin source → $PLUGIN_DIR"
install_plugin_bundle
run "chmod +x $(printf %q "${PLUGIN_DIR}/scripts/")*.sh 2>/dev/null || true"
patch_plugin_hooks
patch_plugin_mcp
write_marketplace

if ! $DRY_RUN; then
    MARKETPLACE_NAME="$(MARKETPLACE_PATH="$CODEX_MARKETPLACE" python3 -c 'import json, os; print(json.load(open(os.environ["MARKETPLACE_PATH"]))["name"])')"
    PLUGIN_ID="atelier@${MARKETPLACE_NAME}"
fi
install_codex_plugin

# ---- AGENTS.md and task templates --------------------------------------------
merge_agents_file "${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md" "$AGENTS_FILE"

TASKS_SRC_DIR="${ATELIER_REPO}/integrations/codex/tasks"
if $WORKSPACE_SET && [ -d "$TASKS_SRC_DIR" ]; then
    run "mkdir -p $(printf %q "$TASKS_DEST_DIR")"
    run "cp $(printf %q "$TASKS_SRC_DIR")/*.md $(printf %q "$TASKS_DEST_DIR/")"
    info "installed task templates: $TASKS_DEST_DIR"
elif $WORKSPACE_SET; then
    warn "task template directory missing: $TASKS_SRC_DIR"
fi

project_custom_agents

if $DRY_RUN; then
    info "Dry run complete; skipping post-install verification."
    exit 0
fi

# ---- post-install verification ------------------------------------------------
info "Running post-install verification..."
VFAIL=0
vpass() { info "PASS: $*"; }
vfail() { echo "[atelier:codex] FAIL: $*" >&2; VFAIL=1; }
vwarn() { warn "$*"; }

if [ -f "${PLUGIN_DIR}/.codex-plugin/plugin.json" ]; then
    vpass "Codex plugin manifest installed: ${PLUGIN_DIR}/.codex-plugin/plugin.json"
else
    vfail "Codex plugin manifest missing: ${PLUGIN_DIR}/.codex-plugin/plugin.json"
fi

if [ -f "${PLUGIN_DIR}/skills/code/SKILL.md" ] && [ -f "${PLUGIN_DIR}/skills/explore/SKILL.md" ]; then
    vpass "Codex skill bundle installed: ${PLUGIN_DIR}/skills"
else
    vfail "Codex skill bundle missing shared mode skills: ${PLUGIN_DIR}/skills"
fi

if [ -f "${PLUGIN_DIR}/agents/openai.yaml" ]; then
    vpass "Codex plugin agent surface installed: ${PLUGIN_DIR}/agents/openai.yaml"
else
    vfail "Codex plugin agent surface missing: ${PLUGIN_DIR}/agents/openai.yaml"
fi

if [ -f "$PLUGIN_MCP_JSON" ]; then
    MCP_STATUS="$(PLUGIN_MCP_JSON_PATH="$PLUGIN_MCP_JSON" python3 - <<'PYEOF'
import json
import os
from pathlib import Path

data = json.loads(Path(os.environ["PLUGIN_MCP_JSON_PATH"]).read_text(encoding="utf-8"))
server = data.get("atelier", {})
print(server.get("command", ""))
print(" ".join(server.get("args") or []))
print((server.get("env") or {}).get("ATELIER_WORKSPACE_ROOT", ""))
PYEOF
)"
    MCP_COMMAND="$(printf '%s\n' "$MCP_STATUS" | sed -n '1p')"
    MCP_ARGS="$(printf '%s\n' "$MCP_STATUS" | sed -n '2p')"
    MCP_WORKSPACE_ROOT="$(printf '%s\n' "$MCP_STATUS" | sed -n '3p')"
    if [ "$MCP_COMMAND" = "atelier" ] && [ "$MCP_ARGS" = "mcp --host codex" ]; then
        vpass "plugin MCP config points at atelier mcp --host codex"
    else
        vfail "plugin MCP config is invalid (command: ${MCP_COMMAND:-unset}; args: ${MCP_ARGS:-unset})"
    fi
    if $WORKSPACE_SET && [ "$MCP_WORKSPACE_ROOT" != "$WORKSPACE" ]; then
        vfail "plugin MCP config expected ATELIER_WORKSPACE_ROOT=$WORKSPACE (got: ${MCP_WORKSPACE_ROOT:-unset})"
    fi
else
    vfail "plugin MCP config missing: $PLUGIN_MCP_JSON"
fi

if [ -f "$CODEX_MARKETPLACE" ]; then
    MARKETPLACE_OK="$(MARKETPLACE_PATH="$CODEX_MARKETPLACE" python3 -c 'import json, os; data=json.load(open(os.environ["MARKETPLACE_PATH"])); print("yes" if any(p.get("name")=="atelier" and p.get("source",{}).get("path")=="./.codex/plugins/atelier" and p.get("policy",{}).get("installation")=="INSTALLED_BY_DEFAULT" for p in data.get("plugins",[])) else "no")')"
    if [ "$MARKETPLACE_OK" = "yes" ]; then
        vpass "marketplace contains restart-installable Atelier entry: $CODEX_MARKETPLACE"
    else
        vfail "marketplace has no valid Atelier entry: $CODEX_MARKETPLACE"
    fi
else
    vfail "marketplace file missing: $CODEX_MARKETPLACE"
fi

PLUGIN_LIST="$(codex_cmd plugin list 2>/dev/null || true)"
if grep -Fq "$PLUGIN_ID" <<<"$PLUGIN_LIST"; then
    vpass "Codex plugin list contains $PLUGIN_ID"
elif grep -qF "[plugins.\"$PLUGIN_ID\"]" "$USER_CODEX_CONFIG" 2>/dev/null; then
    vpass "user Codex config contains $PLUGIN_ID"
else
    vwarn "${PLUGIN_ID} is staged but not active yet; restart Codex and enable it from /plugins."
fi

if [ -f "${PLUGIN_DIR}/hooks/hooks.json" ]; then
    if grep -qF '${PLUGIN_ROOT}/hooks/' "${PLUGIN_DIR}/hooks/hooks.json" && ! grep -qE '__ATELIER_(PYTHON|REPO_SRC)__' "${PLUGIN_DIR}/hooks/hooks.json"; then
        vpass "Codex plugin lifecycle hooks installed: ${PLUGIN_DIR}/hooks/hooks.json"
    else
        vfail "Codex plugin lifecycle hooks do not resolve through PLUGIN_ROOT"
    fi
else
    vfail "Codex plugin lifecycle hooks missing: ${PLUGIN_DIR}/hooks/hooks.json"
fi

if [ -f "${PLUGIN_DIR}/scripts/statusline.sh" ] && [ -x "${PLUGIN_DIR}/scripts/statusline.sh" ]; then
    vpass "Codex statusline script installed and executable"
else
    vwarn "Codex statusline script missing or not executable (optional feature)"
fi

if [ -f "$AGENTS_FILE" ] && grep -q "atelier:code" "$AGENTS_FILE" 2>/dev/null; then
    vpass "AGENTS.md contains Atelier instructions: $AGENTS_FILE"
else
    vfail "AGENTS.md missing or has no atelier:code persona: $AGENTS_FILE"
fi

EXPECTED_AGENT_IDS=(code explore execute plan research review solve)
MISSING_AGENTS=()
for role_id in "${EXPECTED_AGENT_IDS[@]}"; do
    agent_file="${AGENTS_DIR}/atelier.${role_id}.toml"
    if [ ! -f "$agent_file" ] || ! grep -q '^name = ' "$agent_file" || ! grep -q '^developer_instructions = ' "$agent_file"; then
        MISSING_AGENTS+=("$role_id")
    fi
done
if [ "${#MISSING_AGENTS[@]}" -eq 0 ]; then
    vpass "all seven standalone Codex agents installed: ${AGENTS_DIR}"
else
    vfail "missing or invalid Codex agents: ${MISSING_AGENTS[*]}"
fi

if grep -q '^\[agents\.atelier_' "$CODEX_CONFIG" 2>/dev/null; then
    vfail "obsolete per-agent registration blocks remain in $CODEX_CONFIG"
else
    vpass "Codex agents use the current standalone-file discovery format"
fi

if $WORKSPACE_SET; then
    if [ -d "$TASKS_DEST_DIR" ] && [ -f "$TASKS_DEST_DIR/preflight.md" ]; then
        vpass "Codex task templates installed: $TASKS_DEST_DIR"
    else
        vfail "Codex task templates missing in $TASKS_DEST_DIR"
    fi
fi

if command -v atelier >/dev/null 2>&1 && atelier status --help >/dev/null 2>&1; then
    vpass "atelier status command is available"
else
    vfail "atelier status command unavailable"
fi

if [ "$VFAIL" -ne 0 ]; then
    echo "[atelier:codex] ERROR: post-install verification failed." >&2
    exit 1
fi

if $PLUGIN_INSTALL_PENDING; then
    warn "Installation succeeded; plugin activation will complete after Codex restart or manual enablement in /plugins."
fi
info "All required install checks passed"
info "Done. Restart Codex, then spawn agents by name (for example: atelier.explore)."
