# Troubleshooting

## `make verify` Fails with ruff I001 (import-sort)

**Symptom:**

```
src/atelier/some_module.py:1:1: I001 [*] Import block is un-sorted or un-formatted
```

**Fix:**

```bash
cd atelier && uv run ruff check --fix src tests
uv run python -m black src tests
```

Then re-run `make verify`.

## `make verify` Fails with black

**Symptom:**

```
would reformat src/atelier/some_module.py
```

**Fix:**

```bash
cd atelier && uv run python -m black src tests
```

## 9 Tests Skipped — Is That a Failure?

No. The 9 skips are Postgres-gated tests that require `ATELIER_DATABASE_URL` to be set. Expected output:

```
209 passed, 9 skipped
```

To run them:

```bash
ATELIER_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/atelier \
cd atelier && uv run pytest
```

## MCP Server Not Found

**Symptom:**

```
uv run atelier-mcp: No such command
```

**Fix:**

```bash
cd atelier && uv sync --all-extras
```

The `atelier-mcp` entry point is only installed when extras are synced.

## `atelier init` Fails with "Store Already Exists"

**Symptom:**

```
Error: store already exists at .atelier/
```

**Fix** (if re-seeding for demo purposes):

```bash
rm -rf .atelier/
uv run atelier init --seed
```

Or keep existing store and skip seeding:

```bash
uv run atelier init --no-seed
```

## Gemini CLI MCP Tool Not Available

**Symptom:** Atelier tools don't appear in Gemini CLI.

**Cause:** Gemini CLI requires absolute paths in `settings.json`. Relative paths are silently ignored.

**Fix:** Update `~/.config/gemini/settings.json` to use the full absolute path:

```json
&#123;
  "mcpServers": &#123;
    "atelier": &#123;
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/atelier", "atelier-mcp"],
      "env": &#123;
        "ATELIER_STORE_ROOT": "/absolute/path/to/.atelier"
      &#125;
    &#125;
  &#125;
&#125;
```

## check-plan Returns "pass" When It Should Block

**Cause:** The relevant ReasonBlocks have not been seeded.

**Fix:**

```bash
uv run atelier init --seed
```

Verify blocks exist for your domain:

```bash
uv run atelier list-blocks --domain YOUR_DOMAIN
```

## HTTP Service Errors on Startup

**Symptom:**

```
ATELIER_SERVICE_ENABLED is not set or is false
```

**Fix:**

```bash
ATELIER_SERVICE_ENABLED=true make service
```

Or for no-auth development:

```bash
ATELIER_SERVICE_ENABLED=true ATELIER_REQUIRE_AUTH=false make service
```

## pgvector Extension Not Available

**Symptom:**

```
ERROR: extension "vector" is not available
```

pgvector is optional. Without it, all operations work normally — similarity search falls back to SQLite FTS or Postgres `tsvector`. Only install pgvector if you want embedding-based similarity boost.

## Port Already in Use (Frontend/Backend, not Atelier)

See the main project Makefile for port conflict resolution:

```bash
lsof -ti :3125 :8787 | xargs kill -9 2>/dev/null || true
make start
```
