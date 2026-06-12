#!/usr/bin/env bash
set -euo pipefail

echo "◆ Starting Production Bundle..."

# 1. Ensure directories exist without deleting everything
mkdir -p build/ dist/ bundle/bin bundle/frontend bundle/scripts

# 2. Build Frontend
echo "◆ Building Frontend..."
if [ -d "frontend" ]; then
    cd frontend && npm install --silent && npm run build && cd ..
    rm -rf bundle/frontend/*
    cp -r frontend/dist/* bundle/frontend/
fi

# 3. Prepare Build Virtualenv
# Build venv (separate from workspace .venv to exclude benchmark/dev bloat)
BUILD_VENV=".venv-build"
if [ ! -d "$BUILD_VENV" ]; then
    echo "◆ Creating $BUILD_VENV..."
    uv venv "$BUILD_VENV"
fi
PYTHON="$BUILD_VENV/bin/python"
echo "◆ Syncing build venv with project dependencies (including dev)..."
uv pip install --python "$PYTHON" .[dev]

# Remove scipy (119 MB native libs, not needed at runtime; gracefully handled)
echo "◆ Removing scipy from build venv..."
uv pip uninstall --python "$PYTHON" scipy 2>/dev/null || true

# Replace babel with our minimal stub (saves ~32 MB of locale data).
# courlan (trafilatura dep) imports babel only for Locale.parse + UnknownLocaleError.
# The stub at src/atelier/_vendor/babel/ implements exactly that interface.
BABEL_SITE="$BUILD_VENV/lib/python3.13/site-packages/babel"
if [ -d "$BABEL_SITE" ]; then
    echo "◆ Replacing babel with minimal stub (saves ~32 MB)..."
    rm -rf "$BABEL_SITE"
    mkdir -p "$BABEL_SITE"
    cp src/atelier/_vendor/babel/__init__.py "$BABEL_SITE/__init__.py"
fi

# 4. Compile Python Binaries
echo "◆ Compiling Backend Binaries..."
rm -rf bundle/bin/*

# Automatically collect all session parser modules and core capabilities
PARSERS=$(find src/atelier/gateway/hosts/session_parsers -name "*.py" -not -name "__init__.py" -not -name "_*" | \
  sed 's|src/||; s|/|.|g; s|.py||')
CAPS=$(find src/atelier/core/capabilities -name "*.py" -not -name "__init__.py" | \
  sed 's|src/||; s|/|.|g; s|.py||')

# Generate hidden import flags
HIDDEN_IMPORTS=()
for mod in $PARSERS $CAPS; do
    HIDDEN_IMPORTS+=(--hidden-import "$mod")
done

PFLAGS=(
    --noconfirm
    --onedir
    --add-data "src/atelier/infra/storage/migrations/*.sql:atelier/infra/storage/migrations/"
    --add-data "src/atelier/infra/seed_blocks:atelier/infra/seed_blocks"
    --add-data "src/atelier/core/rubrics:atelier/core/rubrics"
    --add-data "src/atelier/infra/code_intel/zoekt/VERSIONS.toml:atelier/infra/code_intel/zoekt/"
    --add-data "src/atelier/core/capabilities/pricing.yaml:atelier/core/capabilities/"
    --add-data "src/atelier/core/service/telemetry/frustration_lexicon.yaml:atelier/core/service/telemetry/"
    --add-data "src/atelier/core/domains/builtin:atelier/core/domains/builtin"
    --add-data "src/atelier/gateway/hosts/configs:atelier/gateway/hosts/configs"
    # hatch force-include data (templates + integrations — not in src/, must pull from venv-build)
    --add-data ".venv-build/lib/python3.13/site-packages/atelier/templates:atelier/templates"
    --add-data ".venv-build/lib/python3.13/site-packages/atelier/integrations:atelier/integrations"
    --add-data ".venv-build/lib/python3.13/site-packages/litellm:litellm"
    --exclude-module benchmarks
    # ── Dev-only tools ────────────────────────────────────────────────────────
    # mypy pulls in ast_serialize (.so) which causes decompression errors.
    --exclude-module mypy
    --exclude-module ast_serialize
    --exclude-module pytest
    --exclude-module ruff
    --exclude-module black
    # ── Large runtime-optional packages ──────────────────────────────────────
    # scipy: removed from venv before PyInstaller runs (see above).
    #        datasketch imports now use direct submodules (minhash.py, hnsw.py)
    #        so datasketch.__init__ never runs, avoiding the scipy-dependent LSH imports.
    --exclude-module scipy
    # hf_xet: optional HuggingFace Xet download accelerator, not used at runtime.
    --exclude-module hf_xet
    # babel: replaced with our minimal stub above — stub is bundled as `babel`.
    #        No --exclude-module needed; PyInstaller picks up the stub automatically.
    --hidden-import ortools
    --hidden-import ortools.sat.python.cp_model
    --hidden-import tiktoken_ext.openai_public
    --hidden-import litellm.litellm_core_utils.tokenizers
    --hidden-import litellm.litellm_core_utils.get_model_cost_map
    "${HIDDEN_IMPORTS[@]}"
)

"$PYTHON" -m PyInstaller "${PFLAGS[@]}" --name atelier \
  --distpath ./build_dist \
  src/atelier/gateway/cli/__main__.py

# --onedir produces build_dist/atelier/{atelier,_internal/,...}
# Place it under bundle/bin/_runtime/ and expose a thin wrapper as bundle/bin/atelier.
# This avoids the zlib decompression failures that --onefile causes with certain
# native extensions (blake3, etc.) while keeping the same distribution layout.
rm -rf bundle/bin/_runtime
cp -r ./build_dist/atelier bundle/bin/_runtime

cat > bundle/bin/atelier <<'WRAPPER'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/_runtime/atelier" "$@"
WRAPPER
chmod +x bundle/bin/atelier

ln -sf atelier bundle/bin/atelierd
ln -sf atelier bundle/bin/atelier-mcp
echo "  $(du -sh bundle/bin/_runtime | awk '{print $1}')"

# 5. Include distribution scripts
echo "◆ Including distribution scripts..."
cp -f scripts/install.sh bundle/scripts/install.sh
cp -f scripts/sessions.sh bundle/scripts/sessions.sh
cp -f scripts/bundle.sh bundle/scripts/bundle.sh

# Pre-generate host context files so install scripts work without uv/Python.
echo "◆ Pre-generating host context files..."
uv run python3 scripts/sync_agent_context.py >/dev/null 2>&1 || true

# Bundle all host integration scripts so install.sh can run them after binary install.
echo "◆ Bundling host integration scripts..."
for s in scripts/install_agent_clis.sh scripts/install_agents.sh \
          scripts/install_antigravity.sh scripts/install_claude.sh \
          scripts/install_codex.sh scripts/install_copilot.sh \
          scripts/install_cursor.sh scripts/install_hermes.sh \
          scripts/install_opencode.sh \
          scripts/build_host_skills.sh scripts/sync_agent_context.py; do
    [[ -f "$s" ]] && cp -f "$s" "bundle/scripts/$(basename "$s")"
done
# sync_agent_context.py resolves ROOT = Path(__file__).parents[1] = bundle/
# and expects host configs at ROOT/src/atelier/gateway/hosts/configs/.
# Provide them at that path so the script can find them without the Python package.
mkdir -p bundle/src/atelier/gateway/hosts/configs
cp -f src/atelier/gateway/hosts/configs/*.yaml bundle/src/atelier/gateway/hosts/configs/
# Bundle lib/ (shared installer functions + managed context helpers).
mkdir -p bundle/scripts/lib
cp -f scripts/lib/common.sh bundle/scripts/lib/common.sh
cp -f scripts/lib/managed_context.sh bundle/scripts/lib/managed_context.sh

# Bundle integration files (pre-generated .md/.json/.sh per-host configs).
echo "◆ Bundling host integration configs..."
mkdir -p bundle/integrations
for host in agents antigravity claude codex copilot copilot-cli cursor hermes opencode shared skills; do
    [[ -d "integrations/$host" ]] && cp -r "integrations/$host" "bundle/integrations/$host"
done

chmod +x bundle/scripts/*.sh 2>/dev/null || true

# 6. Create Archive
echo "◆ Creating Archive..."
mkdir -p dist
OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
ARCHIVE_NAME="dist/atelier-binaries-${OS_NAME}-${ARCH}.tar.gz"

rm -f "$ARCHIVE_NAME"

# Ensure PyInstaller has finished all file operations
sleep 2

tar -czf "$ARCHIVE_NAME" -C bundle .

echo "✓ Production bundle complete: $ARCHIVE_NAME"
