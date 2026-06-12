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
    uv pip install --python "$BUILD_VENV/bin/python" -e . pyinstaller
fi
PYTHON="$BUILD_VENV/bin/python"

# Remove scipy (119 MB native libs, not needed at runtime; gracefully handled)
echo "◆ Removing scipy from build venv..."
uv pip uninstall --python "$PYTHON" scipy -y 2>/dev/null || true

# Patch datasketch __init__.py to make scipy-dependent submodules lazy
DATASKETCH_INIT="$BUILD_VENV/lib/python3.13/site-packages/datasketch/__init__.py"
if [ -f "$DATASKETCH_INIT" ] && ! grep -q "Lazy-load scipy-dependent" "$DATASKETCH_INIT" 2>/dev/null; then
    echo "◆ Patching datasketch for optional scipy..."
    python3 /tmp/patch_datasketch.py "$DATASKETCH_INIT"
fi

# 4. Compile Python Binaries
echo "◆ Compiling Backend Binaries..."
rm -rf bundle/bin/*

# PyInstaller uses the build/ directory to cache dependency analysis.
# We do NOT remove it.

PFLAGS=(
    --noconfirm
    --onefile
    --exclude-module benchmarks
    --hidden-import tiktoken_ext.openai_public
    --hidden-import atelier.core.capabilities.failure_analysis
    --hidden-import atelier.core.capabilities.loop_detection
    --hidden-import atelier.core.capabilities.context_compression
    --hidden-import atelier.core.capabilities.context_reuse
    --hidden-import atelier.core.capabilities.proof_gate.capability
    --hidden-import atelier.core.capabilities.quality_router.capability
    --hidden-import atelier.core.capabilities.semantic_file_memory
    --hidden-import atelier.core.capabilities.tool_supervision
)

"$PYTHON" -m PyInstaller "${PFLAGS[@]}" --name atelier \
  --distpath ./build_dist \
  src/atelier/gateway/cli/__main__.py
mv -f ./build_dist/atelier bundle/bin/
ln -sf atelier bundle/bin/atelierd
ln -sf atelier bundle/bin/atelier-mcp
echo "  $(du -sh bundle/bin/atelier | awk '{print $1}')"

# 5. Include distribution scripts
echo "◆ Including distribution scripts..."
cp -f scripts/install.sh bundle/scripts/install.sh
cp -f scripts/sessions.sh bundle/scripts/sessions.sh
chmod +x bundle/scripts/install.sh bundle/scripts/sessions.sh

# 6. Create Archive
echo "◆ Creating Archive..."
mkdir -p dist
OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
ARCHIVE_NAME="dist/atelier-binaries-${OS_NAME}-${ARCH}.tar.gz"

rm -f "$ARCHIVE_NAME"

tar -czf "$ARCHIVE_NAME" -C bundle .

echo "✓ Production bundle complete: $ARCHIVE_NAME"
echo "  $(du -sh bundle/bin/* | awk '{print $2": "$1}')"
