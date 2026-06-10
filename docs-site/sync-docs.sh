#!/bin/bash
set -e

PORT=${1:-3200}
DOCS_SRC=${2:-/docs}

echo "Syncing public docs from $DOCS_SRC into Docusaurus content..."

# Clear existing docs
rm -rf /app/docs-site/docs/*

# Sync all markdown files from the public docs directory
if [ -d "$DOCS_SRC" ]; then
  rsync -av \
    --include='*/' \
    --include='*.md' \
    --exclude='*' \
    "$DOCS_SRC/" /app/docs-site/docs/
  # Also sync image assets
  rsync -av --include='*/' --include='*.png' --include='*.svg' --include='*.jpg' --exclude='*' \
    "$DOCS_SRC/" /app/docs-site/docs/ 2>/dev/null || true
else
  echo "Warning: $DOCS_SRC not found, skipping sync"
fi

echo "Docs synced. Starting Docusaurus on port $PORT..."

cd /app/docs-site
npm run start -- --host 0.0.0.0 --port $PORT
