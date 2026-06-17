#!/usr/bin/env bash
# Publish a clean-squash public snapshot from this private repository.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/publish-public.sh [options]

Options:
  --dry-run              Build and verify the filtered snapshot, but do not push.
  --yes                  Allow the force-push to the public branch.
  --remote URL           Public repository remote. Default: PUBLIC_REMOTE or https://github.com/atelier-ws/atelier.git
  --branch NAME          Public branch. Default: PUBLIC_BRANCH or main
  --source-ref REF       Git ref to snapshot. Default: PUBLIC_SOURCE_REF or HEAD
  --message TEXT         Snapshot commit message. Default: PUBLIC_COMMIT_MESSAGE or Initial public release
  --private-paths FILE   Denylist file. Default: PRIVATE_PATHS_FILE or release/private-paths.txt
  -h, --help             Show this help.

Environment:
  PUBLIC_REMOTE_TOKEN    Token used for https://github.com/... remotes without embedding it in logs.
EOF
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

trim_path() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value#./}"
    while [[ "$value" == ./* ]]; do
        value="${value#./}"
    done
    value="${value%/}"
    printf '%s' "$value"
}

validate_private_path() {
    local path="$1"
    [[ -n "$path" ]] || die "empty private path in ${PRIVATE_PATHS_FILE}"
    [[ "$path" != /* ]] || die "private path must be repository-relative: $path"
    [[ "$path" != "." ]] || die "private path cannot be repository root"
    [[ "$path" != ".." && "$path" != ../* && "$path" != */../* && "$path" != */.. ]] || die "private path cannot escape repository root: $path"
    [[ "$path" != ".git" && "$path" != .git/* ]] || die "private path cannot target .git: $path"
    [[ "$path" != *'*'* && "$path" != *'?'* && "$path" != *'['* ]] || die "glob syntax is not supported in private paths: $path"
}

load_private_paths() {
    local raw path
    private_paths=()
    while IFS= read -r raw || [[ -n "$raw" ]]; do
        [[ "$raw" =~ ^[[:space:]]*$ ]] && continue
        [[ "$raw" =~ ^[[:space:]]*# ]] && continue
        path="$(trim_path "$raw")"
        validate_private_path "$path"
        private_paths+=("$path")
    done <"$PRIVATE_PATHS_FILE"

    ((${#private_paths[@]} > 0)) || die "no private paths configured in ${PRIVATE_PATHS_FILE}"
}

is_private_path() {
    local rel="$1"
    local private
    rel="$(trim_path "$rel")"
    for private in "${private_paths[@]}"; do
        if [[ "$rel" == "$private" || "$rel" == "$private/"* ]]; then
            return 0
        fi
    done
    return 1
}

filter_snapshot() {
    local private
    for private in "${private_paths[@]}"; do
        if [[ -e "$SNAPSHOT_DIR/$private" || -L "$SNAPSHOT_DIR/$private" ]]; then
            rm -rf -- "$SNAPSHOT_DIR/$private"
        fi
    done
}

verify_snapshot() {
    local item rel
    local -a violations=()
    while IFS= read -r -d '' item; do
        rel="${item#"$SNAPSHOT_DIR/"}"
        if is_private_path "$rel"; then
            violations+=("$rel")
        fi
    done < <(find "$SNAPSHOT_DIR" -mindepth 1 -print0)

    if ((${#violations[@]} > 0)); then
        printf 'error: filtered public snapshot still contains private paths:\n' >&2
        printf '  %s\n' "${violations[@]}" >&2
        exit 1
    fi
}

safe_remote_url() {
    local url="$1"
    if [[ "$url" == https://*"@"* ]]; then
        printf '%s' "$url" | sed -E 's#(https://)[^/@]+@#\1***@#'
    else
        printf '%s' "$url"
    fi
}

remote_with_token() {
    local url="$1"
    if [[ -z "${PUBLIC_REMOTE_TOKEN:-}" ]]; then
        printf '%s' "$url"
        return 0
    fi
    [[ "$url" == https://github.com/* ]] || die "PUBLIC_REMOTE_TOKEN is only supported for https://github.com/... remotes"
    printf 'https://x-access-token:%s@github.com/%s' "$PUBLIC_REMOTE_TOKEN" "${url#https://github.com/}"
}

DRY_RUN="${PUBLISH_DRY_RUN:-0}"
ASSUME_YES="${PUBLISH_CONFIRM:-0}"
PUBLIC_REMOTE="${PUBLIC_REMOTE:-https://github.com/atelier-ws/atelier.git}"
PUBLIC_BRANCH="${PUBLIC_BRANCH:-main}"
# Removed the fixed default here: PUBLIC_COMMIT_MESSAGE="${PUBLIC_COMMIT_MESSAGE:-Initial public release}"
PUBLIC_SOURCE_REF="${PUBLIC_SOURCE_REF:-HEAD}"
PRIVATE_PATHS_FILE="${PRIVATE_PATHS_FILE:-release/private-paths.txt}"

while (($#)); do
    case "$1" in
        # ... (rest of the case statement)
        --message)
            [[ $# -ge 2 ]] || die "--message requires text"
            PUBLIC_COMMIT_MESSAGE="$2"
            shift 2
            ;;
        # ...
    esac
done

# Set a dynamic default if not provided via argument or env var
if [[ -z "${PUBLIC_COMMIT_MESSAGE:-}" ]]; then
    PUBLIC_COMMIT_MESSAGE="Public snapshot for ${PUBLIC_SOURCE_REF}"
fi

need_cmd git
need_cmd tar
need_cmd find
need_cmd mktemp
need_cmd sed

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

[[ -n "$PUBLIC_REMOTE" ]] || die "PUBLIC_REMOTE cannot be empty"
[[ -n "$PUBLIC_BRANCH" ]] || die "PUBLIC_BRANCH cannot be empty"
[[ "$PUBLIC_SOURCE_REF" != -* ]] || die "source ref cannot start with '-': $PUBLIC_SOURCE_REF"
git check-ref-format --branch "$PUBLIC_BRANCH" >/dev/null || die "invalid public branch name: $PUBLIC_BRANCH"
[[ -f "$PRIVATE_PATHS_FILE" ]] || die "private paths file not found: $PRIVATE_PATHS_FILE"
git rev-parse --verify "${PUBLIC_SOURCE_REF}^{tree}" >/dev/null || die "source ref does not exist: $PUBLIC_SOURCE_REF"

load_private_paths

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/atelier-public.XXXXXX")"
SNAPSHOT_DIR="$TMP_DIR/snapshot"
cleanup() {
    rm -rf -- "$TMP_DIR"
}
trap cleanup EXIT
mkdir -p "$SNAPSHOT_DIR"

git archive --format=tar "$PUBLIC_SOURCE_REF" | tar -xf - -C "$SNAPSHOT_DIR"
filter_snapshot
verify_snapshot

git -C "$SNAPSHOT_DIR" init >/dev/null
git -C "$SNAPSHOT_DIR" remote add public "$(remote_with_token "$PUBLIC_REMOTE")"
git -C "$SNAPSHOT_DIR" fetch public "$PUBLIC_BRANCH" --depth 1
git -C "$SNAPSHOT_DIR" checkout -B "$PUBLIC_BRANCH" public/"$PUBLIC_BRANCH" >/dev/null 2>&1 || git -C "$SNAPSHOT_DIR" checkout -B "$PUBLIC_BRANCH"
git -C "$SNAPSHOT_DIR" config user.name "${PUBLIC_GIT_USER_NAME:-Atelier Release Bot}"
git -C "$SNAPSHOT_DIR" config user.email "${PUBLIC_GIT_USER_EMAIL:-release@atelier.local}"

# Clean existing files (except .git) to ensure filtering
find "$SNAPSHOT_DIR" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +

# Copy filtered files back
git archive --format=tar "$PUBLIC_SOURCE_REF" | tar -xf - -C "$SNAPSHOT_DIR"
filter_snapshot
verify_snapshot

git -C "$SNAPSHOT_DIR" add -A
if git -C "$SNAPSHOT_DIR" diff --cached --quiet; then
    printf 'No changes to public snapshot.\n'
    exit 0
fi
git -C "$SNAPSHOT_DIR" commit -m "$PUBLIC_COMMIT_MESSAGE" >/dev/null

COMMIT_SHA="$(git -C "$SNAPSHOT_DIR" rev-parse --short HEAD)"
FILE_COUNT="$(git -C "$SNAPSHOT_DIR" ls-files | wc -l | tr -d ' ')"
printf 'Prepared public snapshot %s with %s files.\n' "$COMMIT_SHA" "$FILE_COUNT"

if [[ "$DRY_RUN" == "1" ]]; then
    printf 'Dry run complete; no push performed. Target would be %s:%s.\n' "$(safe_remote_url "$PUBLIC_REMOTE")" "$PUBLIC_BRANCH"
    exit 0
fi

if [[ "$ASSUME_YES" != "1" ]]; then
    die "refusing to push without --yes"
fi

git -C "$SNAPSHOT_DIR" push public "$PUBLIC_BRANCH"
printf 'Pushed public snapshot %s to %s:%s.\n' "$COMMIT_SHA" "$(safe_remote_url "$PUBLIC_REMOTE")" "$PUBLIC_BRANCH"
