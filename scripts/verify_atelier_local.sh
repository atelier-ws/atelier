#!/usr/bin/env bash
# verify_atelier_local.sh — local quality gate: lint + format + types + tests
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Atelier local verification ==="

echo "--- ruff ---"
uv run ruff check src tests

echo "--- black --check ---"
uv run black --check src tests

echo "--- mypy --strict ---"
uv run mypy --strict src tests

echo "--- pytest ---"
uv run pytest -q

echo "=== PASS: all local checks passed ==="
