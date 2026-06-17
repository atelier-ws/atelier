#!/usr/bin/env bash
# install_codex.sh — Install Atelier into Codex CLI
#
# What it does:
#   Global mode: installs a personal Codex marketplace plus a local Atelier plugin source.
#   Workspace mode (--workspace DIR): installs a repo-local Codex marketplace plus a local Atelier plugin source under DIR.
#
# Options:
#   --dry-run        Print what would happen, touch nothing
#   --print-only     Print config snippets for manual install, touch nothing
#   --workspace DIR  Install project-local artifacts into DIR instead of global user config
#   --strict         Exit nonzero if 'codex' CLI not on PATH

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
source "${SCRIPT_DIR}/lib/managed_context.sh"
PLUGIN_TEMPLATE="${ATELIER_REPO}/integrations/codex/plugin"

DRY_RUN=false
PRINT_ONLY=false
STRICT=false
WORKSPACE=""
WORKSPACE_SET=false

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
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

if $WORKSPACE_SET; then
    WORKSPACE="$(cd "$WORKSPACE" && pwd)"
fi

if $WORKSPACE_SET; then
    INSTALL_SCOPE="workspace"
    CODEX_HOME="${WORKSPACE}/.codex"
    PLUGIN_DIR="${WORKSPACE}/.codex/plugins/atelier"
    AGENTS_FILE="${WORKSPACE}/AGENTS.md"
    TASKS_DEST_DIR="${WORKSPACE}/.codex/tasks"
else
    INSTALL_SCOPE="global"
    CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"
    PLUGIN_DIR="${CODEX_HOME}/plugins/atelier"
    AGENTS_FILE="${CODEX_HOME}/AGENTS.md"
    TASKS_DEST_DIR=""
fi

PLUGIN_MCP_JSON="${PLUGIN_DIR}/.mcp.json"
SKILL_BUILDER="${SCRIPT_DIR}/build_host_skills.sh"
STAGING_DIR="${HOME}/.atelier/codex-plugin"

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
    echo "   cp '${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md' '${PLUGIN_DIR}/agents/atelier.md'"
    echo "   bash '${SKILL_BUILDER}' --host codex --dest '${PLUGIN_DIR}/skills'"
    echo ""
    echo "2. Patch '${PLUGIN_DIR}/hooks/hooks.json' by replacing:"
    echo "   __ATELIER_PYTHON__  -> the Python interpreter used by the atelier launcher"
    echo "   __ATELIER_REPO_SRC__ -> '${ATELIER_REPO}/src'"
    echo ""
    echo "3. Patch ${PLUGIN_MCP_JSON} to use 'atelier mcp --host codex'."
    echo ""
    echo "4. Register Atelier as a Codex MCP server:"
    if $WORKSPACE_SET; then
        echo "   CODEX_HOME='${CODEX_HOME}' codex mcp add atelier --env ATELIER_WORKSPACE_ROOT='${WORKSPACE}' -- atelier mcp --host codex"
    else
        echo "   codex mcp add atelier -- atelier mcp --host codex"
    fi
    echo ""
    echo "5. Register the complete plugin bundle in the personal marketplace:"
    if $WORKSPACE_SET; then
        echo "   # Add atelier to '${WORKSPACE}/.agents/plugins/marketplace.json'"
        echo "   # with source.path './.codex/plugins/atelier', then run:"
    else
        echo "   # Add atelier to '${HOME}/.agents/plugins/marketplace.json'"
        echo "   # with source.path './.codex/plugins/atelier', then run:"
    fi
    echo "   codex plugin add atelier@atelier-local"
    echo ""
    if $WORKSPACE_SET; then
        echo "6. Install universal project agents (run once per project):"
        echo "   bash scripts/install_agents.sh --workspace '${WORKSPACE}'"
        echo ""
        echo "7. Install task templates:"
        echo "   mkdir -p '${TASKS_DEST_DIR}'"
        echo "   cp '${ATELIER_REPO}/integrations/codex/tasks/'*.md '${TASKS_DEST_DIR}/'"
    else
        echo "6. Install Codex instructions:"
        echo "   cp '${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md' '${AGENTS_FILE}'"
    fi
}

# Print-only must be completely side-effect free and should not require Codex.
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
    local agent_src="${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md"
    info "Staging Codex agent instructions"
    run "cp $(printf %q "$agent_src") $(printf %q "$STAGING_DIR/agents/atelier.md")"
    run "bash $(printf %q "$SKILL_BUILDER") --host codex --dest $(printf %q "$STAGING_DIR/skills")"
    PLUGIN_TEMPLATE="$STAGING_DIR"
}

backup_file() {
    local f="$1"
    if $WORKSPACE_SET; then
        return
    fi
    if [ -f "$f" ]; then
        local bk="${f}.atelier-backup.$(date +%Y%m%dT%H%M%S)"
        run "cp $(printf %q "$f") $(printf %q "$bk")"
        info "backed up $f → $bk"
    fi
}

backup_path() {
    local path="$1"
    if $WORKSPACE_SET; then
        return
    fi
    if [ -e "$path" ]; then
        local bk="${path}.atelier-backup.$(date +%Y%m%dT%H%M%S)"
        if [ -d "$path" ]; then
            run "cp -R $(printf %q "$path") $(printf %q "$bk")"
        else
            run "cp $(printf %q "$path") $(printf %q "$bk")"
        fi
        info "backed up $path → $bk"
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

codex_cmd() {
    if $WORKSPACE_SET; then
        CODEX_HOME="$CODEX_HOME" codex "$@"
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

patch_plugin_hooks() {
    if $DRY_RUN; then
        echo "  [dry-run] patch ${PLUGIN_DIR}/hooks/hooks.json with absolute plugin path"
        return
    fi

    local atelier_python
    atelier_python="$(resolve_atelier_hook_python)"

    if [[ "$atelier_python" != /* ]] || [ ! -x "$atelier_python" ]; then
        echo "[atelier:codex] ERROR: cannot resolve Atelier Python interpreter from $atelier_python" >&2
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
    local workspace_mode="0"
    if $WORKSPACE_SET; then
        workspace_mode="1"
    fi
    if $DRY_RUN; then
        echo "  [dry-run] patch $PLUGIN_MCP_JSON to use atelier"
        return
    fi

    PLUGIN_MCP_JSON_PATH="$PLUGIN_MCP_JSON" \
    ATELIER_WORKSPACE_MODE="$workspace_mode" \
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
server["alwaysLoad"] = True
server.pop("cwd", None)
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PYEOF
}

ensure_codex_mcp() {
    run "mkdir -p $(printf %q "$CODEX_HOME")"
    if $DRY_RUN; then
        if $WORKSPACE_SET; then
            echo "  [dry-run] CODEX_HOME='$CODEX_HOME' codex mcp add atelier --env ATELIER_WORKSPACE_ROOT='$WORKSPACE' -- atelier mcp --host codex"
        else
            echo "  [dry-run] codex mcp add atelier -- atelier mcp --host codex"
        fi
        return
    fi

    codex_cmd mcp remove atelier >/dev/null 2>&1 || true
    if $WORKSPACE_SET; then
        codex_cmd mcp add atelier --env "ATELIER_WORKSPACE_ROOT=$WORKSPACE" -- atelier mcp --host codex >/dev/null 2>&1 || warn "codex mcp add failed (config may have other issues); MCP registration skipped"
    else
        codex_cmd mcp add atelier -- atelier mcp --host codex >/dev/null 2>&1 || warn "codex mcp add failed (config may have other issues); MCP registration skipped"
    fi
    if grep -q '\[mcp_servers\.atelier\]' "$CODEX_HOME/config.toml" 2>/dev/null; then
        info "registered Codex MCP server 'atelier' in ${CODEX_HOME}/config.toml"
    fi
}

install_codex_plugin() {
    local marketplace_root marketplace source_path
    if $WORKSPACE_SET; then
        marketplace_root="$WORKSPACE"
    else
        marketplace_root="$HOME"
    fi
    source_path="./.codex/plugins/atelier"
    marketplace="${marketplace_root}/.agents/plugins/marketplace.json"

    if $DRY_RUN; then
        echo "  [dry-run] register atelier in ${marketplace}"
        echo "  [dry-run] codex plugin add atelier@atelier-local"
        return
    fi

    mkdir -p "$(dirname "$marketplace")"
    MARKETPLACE_PATH="$marketplace" PLUGIN_SOURCE_PATH="$source_path" python3 - <<'PYEOF'
import json
import os
from pathlib import Path

path = Path(os.environ["MARKETPLACE_PATH"])
data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"name": "atelier-local", "plugins": []}
data.setdefault("name", "atelier-local")
data.setdefault("interface", {"displayName": "Atelier local"})
entry = {
    "name": "atelier",
    "source": {"source": "local", "path": os.environ["PLUGIN_SOURCE_PATH"]},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Coding",
}
data["plugins"] = [plugin for plugin in data.get("plugins", []) if plugin.get("name") != "atelier"] + [entry]
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PYEOF

    codex_cmd plugin remove atelier@openai-curated >/dev/null 2>&1 || true
    if codex_cmd plugin add atelier@atelier-local >/dev/null 2>&1; then
        info "installed Codex plugin atelier@atelier-local"
    else
        warn "Codex plugin auto-install failed; restart Codex and install atelier@atelier-local from /plugins."
    fi
}

# ---- stage + install plugin bundle -------------------------------------------
stage_plugin_bundle
info "Installing Codex plugin source → $PLUGIN_DIR"
install_plugin_bundle
run "chmod +x $(printf %q "${PLUGIN_DIR}/scripts/")*.sh 2>/dev/null || true"
patch_plugin_hooks
patch_plugin_mcp
ensure_codex_mcp
install_codex_plugin

# ---- auto-approve all Atelier MCP tools in config.toml -----------------------
CODEX_CONFIG="${CODEX_HOME}/config.toml"
if $DRY_RUN; then
    echo "  [dry-run] add Atelier MCP tool auto-approvals to ${CODEX_CONFIG}"
elif [ -f "$CODEX_CONFIG" ]; then
    APPROVE_SCRIPT=$(mktemp "${TMPDIR:-/tmp}/atelier_codex_approve_XXXXXX")
    cat > "${APPROVE_SCRIPT}" <<'PYEOF'
import sys

config_path = sys.argv[1]
with open(config_path, "r") as f:
    content = f.read()

ATELIER_TOOLS = [
    "shell", "read", "grep", "edit", "callees", "codemod",
    "memory", "callers", "explore", "web_fetch", "search", "usages",
]

added = []
for tool in ATELIER_TOOLS:
    section = f'[mcp_servers.atelier.tools.{tool}]'
    if section not in content:
        content += f'\n{section}\napproval_mode = "auto"\n'
        added.append(tool)

with open(config_path, "w") as f:
    f.write(content)

if added:
    print(f"[atelier:codex] Added auto-approval for {len(added)} Atelier tools in {config_path}")
else:
    print("[atelier:codex] Atelier MCP tool approvals already configured")
PYEOF
    python3 "${APPROVE_SCRIPT}" "${CODEX_CONFIG}"
    rm -f "${APPROVE_SCRIPT}"
fi

# ---- statusline (command-backed; tui.status_line schema is version-dependent)
STATUSLINE_SCRIPT="${PLUGIN_DIR}/scripts/statusline.sh"
if $DRY_RUN; then
    echo "  [dry-run] leave Codex tui.status_line unchanged; script installed at ${STATUSLINE_SCRIPT}"
elif grep -q 'status_line' "${CODEX_CONFIG}" 2>/dev/null; then
    info "status_line already configured in ${CODEX_CONFIG}; leaving as-is"
else
    info "Codex tui.status_line schema is version-dependent; script installed at ${STATUSLINE_SCRIPT}"
    info "Use Codex /statusline if your build supports command-backed status lines."
fi

# ---- AGENTS.md ---------------------------------------------------------------
merge_agents_file "${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md" "$AGENTS_FILE"

# ---- task templates ----------------------------------------------------------
TASKS_SRC_DIR="${ATELIER_REPO}/integrations/codex/tasks"
if $WORKSPACE_SET && [ -d "$TASKS_SRC_DIR" ]; then
    run "mkdir -p $(printf %q "$TASKS_DEST_DIR")"
    run "cp $(printf %q "$TASKS_SRC_DIR")/*.md $(printf %q "$TASKS_DEST_DIR/")"
    info "installed task templates: $TASKS_DEST_DIR"
elif $WORKSPACE_SET; then
    warn "task template directory missing: $TASKS_SRC_DIR"
fi

if $WORKSPACE_SET; then
    if $DRY_RUN; then
        echo "  [dry-run] project workspace-local Codex agents into '${WORKSPACE}/.codex/agents'"
    else
        ATELIER_RUNTIME_PYTHON="$(resolve_atelier_runtime_python)"
        ATELIER_WORKSPACE_VALUE="$WORKSPACE" ATELIER_REPO_VALUE="$ATELIER_REPO" \
        PYTHONPATH="${ATELIER_REPO}/src${PYTHONPATH:+:${PYTHONPATH}}" \
        "$ATELIER_RUNTIME_PYTHON" - <<'PYEOF'
import os
from pathlib import Path
from atelier.core.capabilities.workspace_host_overrides import write_workspace_codex_agent_config, write_workspace_codex_agents

workspace = Path(os.environ["ATELIER_WORKSPACE_VALUE"])
repo_root = Path(os.environ["ATELIER_REPO_VALUE"])
written = write_workspace_codex_agents(workspace, repo_root=repo_root)
config = write_workspace_codex_agent_config(workspace, repo_root=repo_root)
print(f"[atelier:codex] projected {len(written)} workspace-local Codex agents into {workspace}/.codex/agents")
print(f"[atelier:codex] registered workspace-local Codex agents in {config}")
PYEOF
    fi
else
    if $DRY_RUN; then
        echo "  [dry-run] project global Codex agents into '${CODEX_HOME}/agents'"
    else
        ATELIER_RUNTIME_PYTHON="$(resolve_atelier_runtime_python)"
        ATELIER_CODEX_HOME_VALUE="$CODEX_HOME" ATELIER_REPO_VALUE="$ATELIER_REPO" \
        PYTHONPATH="${ATELIER_REPO}/src${PYTHONPATH:+:${PYTHONPATH}}" \
        "$ATELIER_RUNTIME_PYTHON" - <<'PYEOF'
import os
from pathlib import Path
from atelier.core.capabilities.workspace_host_overrides import write_codex_agent_config, write_codex_agents

codex_home = Path(os.environ["ATELIER_CODEX_HOME_VALUE"])
repo_root = Path(os.environ["ATELIER_REPO_VALUE"])
written = write_codex_agents(codex_home / "agents", repo_root=repo_root)
config = write_codex_agent_config(codex_home / "config.toml", codex_home / "agents", repo_root=repo_root)
print(f"[atelier:codex] projected {len(written)} global Codex agents into {codex_home}/agents")
print(f"[atelier:codex] registered global Codex agents in {config}")
PYEOF
    fi
fi

if $DRY_RUN; then
    info "Dry run complete; skipping post-install verification."
    exit 0
fi

# ── Post-install verification ------------------------------------------------
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
    vpass "Codex skill bundle installed with shared mode skills: ${PLUGIN_DIR}/skills"
else
    vfail "Codex skill bundle missing shared mode skills: ${PLUGIN_DIR}/skills"
fi

if [ -f "${PLUGIN_DIR}/agents/openai.yaml" ]; then
    vpass "Codex plugin agent surface installed: ${PLUGIN_DIR}/agents/openai.yaml"
else
    vfail "Codex plugin agent surface missing: ${PLUGIN_DIR}/agents/openai.yaml"
fi

if [ -f "$PLUGIN_MCP_JSON" ]; then
    MCP_STATUS=$(PLUGIN_MCP_JSON_PATH="$PLUGIN_MCP_JSON" python3 - <<'PYEOF'
import json
import os
from pathlib import Path

data = json.loads(Path(os.environ["PLUGIN_MCP_JSON_PATH"]).read_text(encoding="utf-8"))
server = data.get("atelier", {})
print(server.get("command", ""))
print((server.get("env") or {}).get("ATELIER_WORKSPACE_ROOT", ""))
PYEOF
)
    MCP_COMMAND=$(printf '%s\n' "$MCP_STATUS" | sed -n '1p')
    MCP_WORKSPACE_ROOT=$(printf '%s\n' "$MCP_STATUS" | sed -n '2p')
    if [ "$MCP_COMMAND" = "atelier" ]; then
        vpass "plugin MCP config points at atelier"
    else
        vfail "plugin MCP config does not point at atelier (got: $MCP_COMMAND)"
    fi
    if $WORKSPACE_SET; then
        if [ "$MCP_WORKSPACE_ROOT" = "$WORKSPACE" ]; then
            vpass "plugin MCP config preserves ATELIER_WORKSPACE_ROOT=$WORKSPACE"
        else
            vfail "plugin MCP config expected ATELIER_WORKSPACE_ROOT=$WORKSPACE (got: ${MCP_WORKSPACE_ROOT:-unset})"
        fi
    elif [ -z "$MCP_WORKSPACE_ROOT" ]; then
        vpass "plugin MCP config does not force a workspace root in global mode"
    else
        vfail "plugin MCP config unexpectedly set ATELIER_WORKSPACE_ROOT=${MCP_WORKSPACE_ROOT}"
    fi
else
    vfail "plugin MCP config missing: $PLUGIN_MCP_JSON"
fi

if [ -f "$CODEX_HOME/config.toml" ] && grep -q '\[mcp_servers\.atelier\]' "$CODEX_HOME/config.toml" 2>/dev/null; then
    vpass "Codex config registers atelier MCP server: $CODEX_HOME/config.toml"
else
    vwarn "Codex config missing atelier MCP server entry; plugin .mcp.json is the primary MCP surface"
fi

if codex_cmd mcp list 2>/dev/null | grep -q '^atelier[[:space:]]'; then
    vpass "codex mcp list exposes atelier server"
else
    vwarn "codex mcp list does not expose atelier server; plugin .mcp.json still active"
fi

if command -v atelier &>/dev/null; then
    vpass "atelier is available on PATH"
else
    vfail "atelier NOT found on PATH"
fi

if $WORKSPACE_SET; then
    CODEX_MARKETPLACE="$WORKSPACE/.agents/plugins/marketplace.json"
else
    CODEX_MARKETPLACE="$HOME/.agents/plugins/marketplace.json"
fi
if [ -f "$CODEX_MARKETPLACE" ]; then
    MARKETPLACE_OK=$(MARKETPLACE_PATH="$CODEX_MARKETPLACE" python3 -c 'import json, os; data = json.loads(open(os.environ["MARKETPLACE_PATH"]).read()); print("yes" if any(p.get("name") == "atelier" and p.get("source", {}).get("path") == "./.codex/plugins/atelier" for p in data.get("plugins", [])) else "no")')
    if [ "$MARKETPLACE_OK" = "yes" ]; then
        vpass "personal marketplace contains atelier entry: $CODEX_MARKETPLACE"
    else
        vfail "personal marketplace has no valid atelier entry: $CODEX_MARKETPLACE"
    fi
else
    vfail "personal marketplace file missing: $CODEX_MARKETPLACE"
fi

PLUGIN_CONFIG_KEY='[plugins."atelier@atelier-local"]'
if [ -f "$CODEX_HOME/config.toml" ] && grep -qF "$PLUGIN_CONFIG_KEY" "$CODEX_HOME/config.toml" 2>/dev/null; then
    vpass "Codex config enables plugin atelier@atelier-local"
else
    vfail "Codex config missing plugin entry for atelier@atelier-local"
fi

PLUGIN_LIST=$(codex_cmd plugin list 2>/dev/null || true)
if grep -Eq '^atelier@atelier-local[[:space:]]+installed, enabled([[:space:]]|$)' <<<"$PLUGIN_LIST"; then
    vpass "codex plugin list shows atelier plugin installed"
else
    vfail "codex plugin list does not show atelier@atelier-local installed and enabled"
fi

if [ -f "${PLUGIN_DIR}/hooks/hooks.json" ]; then
    if grep -qF '${PLUGIN_ROOT}/hooks/' "${PLUGIN_DIR}/hooks/hooks.json" && ! grep -qE '__ATELIER_(PYTHON|REPO_SRC)__' "${PLUGIN_DIR}/hooks/hooks.json"; then
        vpass "Codex plugin lifecycle hooks installed with supported plugin-root paths: ${PLUGIN_DIR}/hooks/hooks.json"
    else
        vfail "Codex plugin lifecycle hooks do not resolve through PLUGIN_ROOT"
    fi
else
    vfail "Codex plugin lifecycle hooks missing: ${PLUGIN_DIR}/hooks/hooks.json"
fi

if [ -f "${PLUGIN_DIR}/scripts/statusline.sh" ] && [ -x "${PLUGIN_DIR}/scripts/statusline.sh" ]; then
    vpass "Codex statusline script installed and executable: ${PLUGIN_DIR}/scripts/statusline.sh"
else
    vwarn "Codex statusline script missing or not executable (optional feature)"
fi

if [ -f "$AGENTS_FILE" ] && grep -q "atelier:code" "$AGENTS_FILE" 2>/dev/null; then
    vpass "AGENTS.md present with atelier:code persona: $AGENTS_FILE"
else
    vfail "AGENTS.md missing or has no atelier:code persona: $AGENTS_FILE"
fi

if $WORKSPACE_SET; then
    CODEX_AGENTS_DIR="${WORKSPACE}/.codex/agents"
else
    CODEX_AGENTS_DIR="${CODEX_HOME}/agents"
fi
if [ -f "${CODEX_AGENTS_DIR}/atelier.code.toml" ]; then
    vpass "Codex per-role agents installed: ${CODEX_AGENTS_DIR}"
else
    vfail "Codex per-role agents missing in ${CODEX_AGENTS_DIR}"
fi

if grep -q '^\[agents\.atelier_code\]' "${CODEX_CONFIG}" 2>/dev/null && grep -q 'config_file = ".*/agents/atelier.code.toml"' "${CODEX_CONFIG}" 2>/dev/null; then
    vpass "Codex per-role agents registered in config.toml"
else
    vfail "Codex per-role agents not registered in config.toml"
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
info "All post-install checks passed"

info "Done. Restart Codex — the Atelier marketplace and plugin source are ready."
