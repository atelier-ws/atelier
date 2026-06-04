#!/usr/bin/env bash
set -euo pipefail

echo "◆ Starting Production Bundle (Caching Enabled)..."

# 1. Ensure directories exist without deleting everything
mkdir -p build/ dist/ bundle/bin bundle/frontend

# 2. Build Frontend
echo "◆ Building Frontend..."
if [ -d "frontend" ]; then
    # npm install will only update if needed
    cd frontend && npm install --silent && npm run build && cd ..
    rm -rf bundle/frontend/*
    cp -r frontend/dist/* bundle/frontend/
fi

# 3. Compile Python Binaries
echo "◆ Compiling Backend Binaries..."

# PyInstaller uses the build/ directory to cache dependency analysis.
# We do NOT remove it.

.venv/bin/python -m PyInstaller --noconfirm --onefile --name atelier \
  --distpath ./build_dist \
  src/atelier/gateway/cli/__main__.py
mv -f ./build_dist/atelier bundle/bin/

.venv/bin/python -m PyInstaller --noconfirm --onefile --name atelier-mcp \
  --distpath ./build_dist \
  src/atelier/gateway/adapters/web_fetch_mcp_server.py
mv -f ./build_dist/atelier-mcp bundle/bin/

# 4. Create Archive
echo "◆ Creating Archive..."
mkdir -p dist
OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
ARCHIVE_NAME="dist/atelier-binaries-${OS_NAME}-${ARCH}.tar.gz"

# Remove only the specific old archive
rm -f "$ARCHIVE_NAME"

tar -czf "$ARCHIVE_NAME" -C bundle .

echo "✓ Production bundle complete: $ARCHIVE_NAME"
