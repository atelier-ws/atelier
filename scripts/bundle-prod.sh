#!/usr/bin/env bash
set -euo pipefail

echo "◆ Starting Production Bundle..."

# 1. Clean
rm -rf build/ dist/ bundle/
mkdir -p bundle/bin bundle/frontend

# 2. Build Frontend
echo "◆ Building Frontend..."
# Check if frontend exists and build it.
if [ -d "frontend" ]; then
    cd frontend && npm install --silent && npm run build && cd ..
    cp -r frontend/dist/* bundle/frontend/
fi

# 3. Compile Python Binaries
echo "◆ Compiling Backend Binaries..."
# Ensure pyinstaller is available
if ! .venv/bin/python -c "import PyInstaller" >/dev/null 2>&1; then
    echo "PyInstaller not found. Installing..."
    .venv/bin/pip install pyinstaller
fi

.venv/bin/python -m PyInstaller --noconfirm --onefile --name atelier \
  src/atelier/gateway/cli/__main__.py
mv dist/atelier bundle/bin/

.venv/bin/python -m PyInstaller --noconfirm --onefile --name atelier-mcp \
  src/atelier/gateway/adapters/web_fetch_mcp_server.py
mv dist/atelier-mcp bundle/bin/

# 4. Create Archive
echo "◆ Creating Archive..."
mkdir -p dist
OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
ARCHIVE_NAME="dist/atelier-binaries-${OS_NAME}-${ARCH}.tar.gz"

tar -czf "$ARCHIVE_NAME" -C bundle .

echo "✓ Production bundle complete: $ARCHIVE_NAME"
