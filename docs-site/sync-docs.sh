#!/bin/bash
set -e

PORT=${1:-3200}

echo "Syncing public docs into Docusaurus content..."
node sync-docs.mjs

echo "Starting Docusaurus on port $PORT..."
npm run start -- --host 0.0.0.0 --port $PORT
