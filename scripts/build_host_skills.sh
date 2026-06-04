#!/usr/bin/env bash
# build_host_skills.sh — Generate host skill bundles from the shared packaged skill bundle
#
# Usage:
#   bash scripts/build_host_skills.sh --host codex
#   bash scripts/build_host_skills.sh --host codex --dest /tmp/codex-skills
#   bash scripts/build_host_skills.sh --host all

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_SRC="${ATELIER_REPO}/integrations/skills"
RENDER_SCRIPT="${SCRIPT_DIR}/sync_agent_context.py"
ALWAYS_EXCLUDED_SKILLS=("trace")
CLAUDE_ROLE_SKILLS=("code" "execute" "explore" "plan" "research" "review" "solve")

HOST=""
DEST=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --host" >&2
                exit 1
            fi
            HOST="$2"
            shift
            ;;
        --dest)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --dest" >&2
                exit 1
            fi
            DEST="$2"
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
    shift
done

if [[ -z "$HOST" ]]; then
    echo "--host is required (claude | codex | antigravity | all)" >&2
    exit 1
fi

uv run python "$RENDER_SCRIPT" >/dev/null

if [[ ! -d "$SKILLS_SRC" ]]; then
    echo "Shared packaged skills directory not found: $SKILLS_SRC" >&2
    exit 1
fi

HIDDEN_SKILLS=()
while IFS= read -r skill_name; do
    [[ -n "$skill_name" ]] && HIDDEN_SKILLS+=("$skill_name")
done < <(
    PYTHONPATH="${ATELIER_REPO}/src:${PYTHONPATH:-}" uv run python - <<'PY'
from atelier.core.environment import HIDDEN_SKILLS

for name in sorted(HIDDEN_SKILLS):
    print(name)
PY
)

is_hidden_skill() {
    local name="$1"
    local skill
    for skill in "${HIDDEN_SKILLS[@]}"; do
        if [[ "$skill" == "$name" ]]; then
            return 0
        fi
    done
    return 1
}

is_always_excluded_skill() {
    local name="$1"
    local skill
    for skill in "${ALWAYS_EXCLUDED_SKILLS[@]}"; do
        if [[ "$skill" == "$name" ]]; then
            return 0
        fi
    done
    return 1
}

is_claude_role_skill() {
    local name="$1"
    local skill
    for skill in "${CLAUDE_ROLE_SKILLS[@]}"; do
        if [[ "$skill" == "$name" ]]; then
            return 0
        fi
    done
    return 1
}

default_dest_for_host() {
    case "$1" in
        claude) printf "%s" "${ATELIER_REPO}/integrations/claude/plugin/skills" ;;
        codex) printf "%s" "${ATELIER_REPO}/integrations/codex/plugin/skills" ;;
        antigravity) printf "%s" "${ATELIER_REPO}/integrations/antigravity/skills" ;;
        *)
            echo "Unknown host: $1" >&2
            exit 1
            ;;
    esac
}

render_host_bundle() {
    local host="$1"
    local dest_dir="$2"
    local skill_dir
    local skill_name

    mkdir -p "$dest_dir"
    find "$dest_dir" -mindepth 1 -maxdepth 1 \
        ! -name ".gitignore" \
        ! -name "README.md" \
        -exec rm -rf {} +

    while IFS= read -r skill_dir; do
        [[ -n "$skill_dir" ]] || continue
        skill_name="$(basename "$skill_dir")"
        if [[ ! -f "$skill_dir/SKILL.md" ]]; then
            continue
        fi
        if is_always_excluded_skill "$skill_name"; then
            continue
        fi
        if is_hidden_skill "$skill_name"; then
            continue
        fi
        if [[ "$host" == "claude" ]] && is_claude_role_skill "$skill_name"; then
            continue
        fi

        mkdir -p "$dest_dir/$skill_name"
        cp "$skill_dir/SKILL.md" "$dest_dir/$skill_name/SKILL.md"
    done < <(find "$SKILLS_SRC" -mindepth 1 -maxdepth 1 -type d | sort)

    echo "[atelier:skills] generated ${host} bundle -> ${dest_dir}"
}

if [[ "$HOST" == "all" ]]; then
    if [[ -n "$DEST" ]]; then
        echo "--dest cannot be used with --host all" >&2
        exit 1
    fi
    render_host_bundle "claude" "$(default_dest_for_host claude)"
    render_host_bundle "codex" "$(default_dest_for_host codex)"
    render_host_bundle "antigravity" "$(default_dest_for_host antigravity)"
    exit 0
fi

if [[ -z "$DEST" ]]; then
    DEST="$(default_dest_for_host "$HOST")"
fi

render_host_bundle "$HOST" "$DEST"
