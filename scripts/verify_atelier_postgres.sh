#!/usr/bin/env bash
# verify_atelier_postgres.sh — Postgres/pgvector smoke test (skip if no URL set)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${ATELIER_DATABASE_URL:-}" ]; then
    echo "SKIPPED: ATELIER_DATABASE_URL not set"
    echo "Set ATELIER_DATABASE_URL=postgresql://user:pass@host/db to run"
    exit 0
fi

python3 -c "import psycopg" 2>/dev/null || {
    echo "SKIPPED: psycopg not installed"
    echo "Install with: uv sync --extra postgres"
    exit 0
}

echo "=== Atelier Postgres verification ==="
export ATELIER_STORAGE_BACKEND=postgres

ROOT=$(mktemp -d)
trap "rm -rf $ROOT" EXIT

echo "--- PostgresStore connectivity ---"
uv run python3 - <<PYEOF
import os
from atelier.infra.storage.postgres_store import PostgresStore

url = os.environ["ATELIER_DATABASE_URL"]
store = PostgresStore(database_url=url)
store.init_schema()
print(f"PASS: connected and schema initialised ({url})")
PYEOF

echo "--- enqueue and claim job ---"
uv run python3 - <<PYEOF
import os
from atelier.infra.storage.postgres_store import PostgresStore
from atelier.core.service.jobs import JOB_ANALYZE_FAILURES

url = os.environ["ATELIER_DATABASE_URL"]
store = PostgresStore(database_url=url)
store.init_schema()

jid = store.enqueue_job(JOB_ANALYZE_FAILURES, {"test": True})
print(f"enqueued job: {jid}")

job = store.claim_job()
assert job is not None, "Expected to claim a job"
assert job.id == jid
store.complete_job(job.id)
print(f"PASS: job enqueue/claim/complete cycle succeeded")
PYEOF

echo "--- pgvector extension (optional) ---"
uv run python3 - <<PYEOF || echo "WARN: pgvector extension not available (non-fatal)"
import os
import psycopg
url = os.environ["ATELIER_DATABASE_URL"]
with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_available_extensions WHERE name='vector'")
        row = cur.fetchone()
        if row:
            print("PASS: pgvector extension available")
        else:
            print("WARN: pgvector extension not installed in this Postgres instance")
PYEOF

echo "=== PASS: Postgres checks passed ==="
