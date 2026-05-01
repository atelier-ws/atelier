# Storage

## Overview

Atelier supports two storage backends:

| Backend               | Default  | Use case                                    |
| --------------------- | -------- | ------------------------------------------- |
| SQLite + FTS5         | Yes      | Single-machine, zero-config, any developer  |
| PostgreSQL + pgvector | Optional | Shared/production, multi-agent, large scale |

The SQLite backend is intentionally the default. Zero infrastructure, zero config, works out of the box.

## SQLite (Default)

```
.atelier/
├── atelier.db          # Main SQLite database
├── blocks/
│   ├── rb_shopify_publish_gid.md
│   ├── rb_pdp_audit_schema.md
│   └── ...             # One .md per ReasonBlock
├── rubrics/
│   ├── rubric_shopify_publish.yaml
│   └── ...             # One .yaml per Rubric
└── traces/
    ├── trace_20260421_abc123.json
    └── ...             # One .json per Trace
```

### Schema

Tables in `atelier.db`:

| Table               | Description                                  |
| ------------------- | -------------------------------------------- |
| `reason_blocks`     | Block metadata + procedure text              |
| `reason_blocks_fts` | FTS5 virtual table over title+procedure      |
| `rubrics`           | Rubric definitions with check lists          |
| `traces`            | Execution traces (observable only)           |
| `audit_log`         | Immutable append-only audit of all mutations |
| `run_ledger`        | Per-run state for long-running sessions      |
| `failure_clusters`  | Clustered failure patterns                   |
| `eval_cases`        | Eval test cases                              |

### Markdown Mirrors

Every ReasonBlock is mirrored to `.atelier/blocks/<id>.md` on upsert (when `write_markdown=True`, which is the default via CLI/MCP). This means blocks can be reviewed in git diffs like any other file.

Similarly, rubrics are mirrored to `.atelier/rubrics/<id>.yaml` and traces to `.atelier/traces/<id>.json`.

These mirrors are **read-only reference copies**. The SQLite database is the source of truth. Edits to `.md`/`.yaml`/`.json` files are not auto-synced back.

## PostgreSQL (Optional)

For shared use, multi-agent concurrency, or when you have 1000+ blocks and want embedding-based search:

```bash
ATELIER_STORAGE_BACKEND=postgres \
ATELIER_DATABASE_URL=postgresql://user:pass@host:5432/atelier \
uv run atelier init
```

### pgvector Extension (Optional)

Enable pgvector for embedding-based similarity search alongside FTS (additive, not a replacement):

```bash
ATELIER_STORAGE_BACKEND=postgres \
ATELIER_DATABASE_URL=postgresql://... \
ATELIER_VECTOR_SEARCH_ENABLED=true \
ATELIER_EMBEDDING_MODEL=text-embedding-3-small \
ATELIER_EMBEDDING_DIM=1536 \
uv run atelier init
```

**Note:** pgvector is an enhancement. The system works without it. Do not add pgvector just to have vectors — add it only when you have 100+ blocks and FTS quality is insufficient.

## Choosing a Backend

| Situation                   | Recommendation                         |
| --------------------------- | -------------------------------------- |
| Solo developer, one machine | SQLite (default)                       |
| Team, shared store          | PostgreSQL                             |
| CI/CD (tests)               | SQLite (ephemeral)                     |
| Production multi-agent      | PostgreSQL                             |
| 1–100 blocks                | SQLite + FTS5 (perfect)                |
| 100–1000+ blocks            | PostgreSQL + pgvector (optional boost) |

## Backup

SQLite:

```bash
cp .atelier/atelier.db .atelier/atelier.db.bak
```

PostgreSQL:

```bash
pg_dump atelier > atelier_backup.sql
```

## Storage Configuration Reference

| Variable                        | Default                  | Description            |
| ------------------------------- | ------------------------ | ---------------------- |
| `ATELIER_ROOT`                  | `.atelier`               | Store root directory   |
| `ATELIER_STORAGE_BACKEND`       | `sqlite`                 | `sqlite` or `postgres` |
| `ATELIER_DATABASE_URL`          | `""`                     | PostgreSQL DSN         |
| `ATELIER_VECTOR_SEARCH_ENABLED` | `false`                  | Enable pgvector        |
| `ATELIER_EMBEDDING_DIM`         | `1536`                   | Embedding dimension    |
| `ATELIER_EMBEDDING_MODEL`       | `text-embedding-3-small` | Embedding model        |
