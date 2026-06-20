#!/usr/bin/env bash
# Zero-LLM setup preflight (bundle variant). Replicates the agent install using
# the prebuilt atelier bundle and verifies claude + atelier as the bench user.
# NEVER invokes the agent/LLM -> zero AI credits.
#   docker run --rm -v <repo>:/atelier:ro -v <bundle>:/atelier-bundle.tar.gz:ro <IMAGE> \
#       bash /atelier/benchmarks/harbor/setup_preflight.sh <LABEL>
set +e
LABEL="${1:-image}"
fail(){ echo "RESULT:$LABEL:FAIL:$1"; exit 1; }

i=0; while :; do apt-get update -qq && apt-get install -y -qq git curl ca-certificates gnupg && break; i=$((i+1)); [ $i -ge 3 ] && fail apt; sleep 3; done

i=0; while :; do curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y -qq nodejs && break; i=$((i+1)); [ $i -ge 3 ] && fail node; sleep 3; done
node -v | grep -qE 'v(1[89]|[2-9][0-9])' || fail "node_$(node -v 2>&1)"

tar -C /opt -xzf /atelier-bundle.tar.gz || fail bundle_extract
chmod -R a+rX /opt/atelier-venv /opt/uvpy
ln -sf /opt/atelier-venv/bin/atelier /usr/local/bin/atelier
/opt/atelier-venv/bin/python -c 'import atelier' || fail import_atelier

i=0; while :; do npm install -g @anthropic-ai/claude-code >/dev/null 2>&1 && break; i=$((i+1)); [ $i -ge 3 ] && fail npm_claude; sleep 3; done
command -v claude >/dev/null || fail claude_bin

useradd -m bench 2>/dev/null || true
runuser -u bench -- /opt/atelier-venv/bin/python -c 'import atelier' || fail bench_import
runuser -u bench -- bash -c 'cd /home/bench && ATELIER_ROOT=/home/bench/.atelier /opt/atelier-venv/bin/atelier init' >/dev/null 2>&1 || fail bench_init

# Prewarm path (the run-time `atelier code index` step). Exercises tree-sitter
# native parsing on this image's glibc. The FTS index grep reads must build for
# (a) a git repo, (b) a NON-git dir with files (many TB workdirs are not git),
# and (c) an empty dir must not abort (exit 0). On a non-git dir the git-history
# pass logs a *caught* GitError (exit stays 0) -- benign -- so we gate on exit
# code and files_indexed, never on the presence of a traceback string.
idx_files(){ /opt/atelier-venv/bin/python -c "import json,sys; print(json.load(open(sys.argv[1])).get('files_indexed',-1))" "$1" 2>/dev/null; }

# (a) git repo -> indexes, exit 0
IDXG=/tmp/idxgit
mkdir -p "$IDXG"
printf 'def alpha():\n    return 1\n' > "$IDXG/a.py"
printf 'from a import alpha\ndef beta():\n    return alpha()\n' > "$IDXG/b.py"
chown -R bench:bench "$IDXG"
runuser -u bench -- bash -c "cd $IDXG && git init -q && git config user.email b@b && git config user.name b && git add -A && git commit -qm init" >/dev/null 2>&1
runuser -u bench -- bash -c "cd $IDXG && export ATELIER_ROOT=/home/bench/.atelier; /opt/atelier-venv/bin/atelier code index --reindex --json" >/tmp/idxg.json 2>/tmp/idxg.err || fail "code_index_git:$(tail -c 200 /tmp/idxg.err)"
[ "$(idx_files /tmp/idxg.json)" -ge 1 ] 2>/dev/null || fail "index_git_zero:$(head -c 200 /tmp/idxg.json)"

# (b) NON-git dir with files -> still indexes (FTS does not need git), exit 0
IDXN=/tmp/idxnogit
mkdir -p "$IDXN"
printf 'def gamma():\n    return 2\n' > "$IDXN/c.py"
chown -R bench:bench "$IDXN"
runuser -u bench -- bash -c "cd $IDXN && export ATELIER_ROOT=/home/bench/.atelier; /opt/atelier-venv/bin/atelier code index --reindex --json" >/tmp/idxn.json 2>/tmp/idxn.err || fail "code_index_nogit:$(tail -c 200 /tmp/idxn.err)"
[ "$(idx_files /tmp/idxn.json)" -ge 1 ] 2>/dev/null || fail "index_nogit_zero:$(head -c 200 /tmp/idxn.json)"

# (c) empty dir -> must not abort (exit 0); no real crash (segfault) allowed
IDXE=/tmp/idxempty
mkdir -p "$IDXE"; chown -R bench:bench "$IDXE"
runuser -u bench -- bash -c "cd $IDXE && export ATELIER_ROOT=/home/bench/.atelier; /opt/atelier-venv/bin/atelier code index --reindex --no-stats" >/dev/null 2>/tmp/idxe.err
EMPTYRC=$?
[ "$EMPTYRC" -eq 0 ] || fail "code_index_empty_rc$EMPTYRC:$(tail -c 200 /tmp/idxe.err)"
grep -qiE 'Segmentation|core dumped' /tmp/idxe.err && fail code_index_empty_segfault

echo "RESULT:$LABEL:PASS node=$(node -v) idx_git=$(idx_files /tmp/idxg.json) idx_nogit=$(idx_files /tmp/idxn.json) emptyrc=$EMPTYRC"
