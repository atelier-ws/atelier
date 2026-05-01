# MCP Server

Atelier ships a full MCP (Model Context Protocol) server that any compatible AI agent host can use.

## Starting the Server

```bash
uv run atelier-mcp
```

Or with an explicit root:

```bash
uv run atelier-mcp --root /path/to/.atelier
```

The server speaks JSON-RPC 2.0 over stdio. It is designed to be spawned by the agent host process, not run as a persistent daemon.

## Modes

| Mode              | Set via                   | Description                          |
| ----------------- | ------------------------- | ------------------------------------ |
| `local` (default) | `ATELIER_MCP_MODE=local`  | Talks directly to local SQLite store |
| `remote`          | `ATELIER_MCP_MODE=remote` | Forwards calls to the HTTP service   |

Remote mode is used when a team shares a central Atelier instance:

```bash
ATELIER_MCP_MODE=remote \
ATELIER_SERVICE_URL=http://atelier.internal:8787 \
ATELIER_API_KEY=my-key \
uv run atelier-mcp
```

## Tool Registry

### V1 Tools (Core — Always Present)

| Tool                            | Description                                          |
| ------------------------------- | ---------------------------------------------------- |
| `atelier_get_reasoning_context` | Get context prompt for a task (blocks + environment) |
| `atelier_check_plan`            | Validate a plan against dead ends and constraints    |
| `atelier_rescue_failure`        | Get rescue procedure for a repeated failure          |
| `atelier_run_rubric_gate`       | Run a rubric gate and get pass/blocked result        |
| `atelier_record_trace`          | Record an execution trace                            |
| `atelier_search`                | Full-text search across blocks                       |

### V2 Tools (Extended — Always Present)

| Tool                              | Description                                 |
| --------------------------------- | ------------------------------------------- |
| `atelier_get_run_ledger`          | Read per-run state ledger                   |
| `atelier_update_run_ledger`       | Update per-run state ledger                 |
| `atelier_monitor_event`           | Emit a monitoring event                     |
| `atelier_compress_context`        | Compress context to reduce token usage      |
| `atelier_get_environment`         | Get a reasoning environment by ID           |
| `atelier_get_environment_context` | Get formatted environment context           |
| `atelier_smart_read`              | Read file with smart truncation (FTS-aware) |
| `atelier_smart_search`            | Search files with result caching            |
| `atelier_cached_grep`             | Grep with injection guard and caching       |

## Tool Schemas

Tools accept and return JSON. Key patterns:

### `atelier_check_plan`

```json
{
  "task": "Publish Shopify product",
  "domain": "beseam.shopify.publish",
  "steps": ["Parse product handle from URL", "Update metafields"]
}
```

Returns: `{"status": "blocked"|"pass", "warnings": [...], "suggestions": [...]}`

### `atelier_record_trace`

```json
{
  "agent": "claude-code",
  "domain": "beseam.shopify.publish",
  "task": "Publish product GID 123",
  "status": "success",
  "commands_run": ["shopify.get_product", "shopify.update_metafield"],
  "errors_seen": [],
  "diff_summary": "Updated metafields",
  "output_summary": "Product published, audit passed"
}
```

### `atelier_run_rubric_gate`

```json
{
  "rubric_id": "rubric_shopify_publish",
  "checks": {
    "product_identity_uses_gid": true,
    "pre_publish_snapshot_exists": true,
    "write_result_checked": true,
    "post_publish_refetch_done": true,
    "post_publish_audit_passed": true,
    "rollback_available": true,
    "localized_url_test_passed": true,
    "changed_handle_test_passed": true
  }
}
```

Returns: `{"status": "pass"|"blocked", "failed_checks": [...]}`

## Verifying the MCP Server

```bash
# Quick verify (tools/list)
cd atelier && make verify-mcp

# Manual test
echo '{"jsonrpc":"2.0","method":"tools/list","id":1}' | uv run atelier-mcp
```

Expected: a `tools/list` response containing all V1 + V2 tools.

## Configuration

| Variable                 | Default                 | Description                                   |
| ------------------------ | ----------------------- | --------------------------------------------- |
| `ATELIER_ROOT`           | `.atelier`              | Store root                                    |
| `ATELIER_WORKSPACE_ROOT` | `.`                     | Workspace root (for relative path resolution) |
| `ATELIER_MCP_MODE`       | `local`                 | `local` or `remote`                           |
| `ATELIER_SERVICE_URL`    | `http://localhost:8787` | Remote service URL (when mode=remote)         |
| `ATELIER_API_KEY`        | `""`                    | API key for remote mode                       |
