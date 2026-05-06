# Quickstart — Atelier in 5 Minutes

This guide gets Atelier running in a fresh project in under 5 minutes.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) installed

## Step 1 — Install

```bash
cd atelier
uv sync --all-extras
```

## Step 2 — Initialize the store

```bash
uv run atelier init
```

This creates `.atelier/` with:

- `atelier.db` — SQLite store with FTS5 search
- `blocks/` — 10 pre-seeded ReasonBlocks (Shopify publish, PDP audit, tracker classification, and more)
- `rubrics/` — 5 pre-seeded rubrics including `rubric_shopify_publish`
- `traces/` — empty, will fill as agents run

## Step 3 — Check a plan

The core feature: block dangerous agent plans _before_ execution.

```bash
uv run atelier lint \
    --task "Publish Shopify product" \
    --domain beseam.shopify.publish \
    --step "Parse product handle from PDP URL" \
    --step "Use handle to update metafields"
```

Expected output:

```
status: blocked
exit: 2
warnings:
  - dead end: product handle from pdp (use product gid instead)
  - dead end: lookup product by handle (shopify api requires gid for writes)
```

Now try a safe plan:

```bash
uv run atelier lint \
    --task "Publish Shopify product" \
    --domain beseam.shopify.publish \
    --step "Fetch product by GID via GraphQL" \
    --step "Snapshot current state" \
    --step "Update metafields with GID" \
    --step "Re-fetch and audit post-publish"
```

Expected: `status: pass` (exit 0)

## Step 4 — Get reasoning context

Before an agent starts a task, inject relevant procedures into its context:

```bash
uv run atelier reasoning \
    --task "Fix Shopify JSON-LD availability validation" \
    --domain beseam.pdp.schema \
    --file pdp/schema.py
```

This returns a structured prompt block with relevant ReasonBlocks, known dead ends, and environment constraints.

## Step 5 — Run a rubric gate

After an agent completes a task, verify it met all required checks:

```bash
echo '&#123;
  "product_identity_uses_gid": true,
  "pre_publish_snapshot_exists": true,
  "write_result_checked": true,
  "post_publish_refetch_done": true,
  "post_publish_audit_passed": true,
  "rollback_available": true,
  "localized_url_test_passed": false,
  "changed_handle_test_passed": false
&#125;' | uv run atelier verify rubric_shopify_publish
```

Expected: `status: blocked` (because localized_url_test_passed = false).

## Step 6 — Record a trace

After an agent run (success or failure), record what happened:

```bash
echo '&#123;
  "agent": "claude-code",
  "domain": "beseam.shopify.publish",
  "task": "Publish product ID 123 to Shopify",
  "status": "success",
  "commands_run": ["shopify.get_product", "shopify.update_metafield", "shopify.get_product"],
  "errors_seen": [],
  "diff_summary": "Updated metafields for product gid://shopify/Product/123",
  "output_summary": "Product published, audit passed"
&#125;' | uv run atelier trace record
```

## Step 7 — Extract a ReasonBlock from a trace

When an agent solves something non-obviously, capture the pattern for future runs:

```bash
uv run atelier trace list
# → find the trace ID

uv run atelier block extract <trace-id>
# → shows candidate block with confidence score

uv run atelier block extract <trace-id> --save
# → saves to store and markdown mirror
```

## Step 8 — Use smart runtime commands

```bash
# Smart retrieval across ReasonBlocks
uv run atelier search "shopify publish validation"

# AST-aware file read with symbol summary
uv run atelier read src/atelier/gateway/adapters/runtime.py --max-lines 120

# Batch edit input format: [{"path": "...", "find": "...", "replace": "..."}]
uv run atelier edit --input edits.json
```

## Next Steps

- **Connect to your AI agent host**: [docs/hosts/](hosts/)
- **Full CLI reference**: [docs/cli.md](cli.md)
- **Core architecture docs**: [docs/core/](core/)
- **Storage and configuration**: [docs/installation.md](installation.md)
- **Engineering details**: [docs/engineering/](engineering/)
