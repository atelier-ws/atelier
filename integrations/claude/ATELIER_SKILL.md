# Atelier Skill — Agent Reasoning Runtime

Use this skill to make your coding more reliable by leveraging the Atelier reasoning runtime.

## Activation

This skill activates automatically when you receive coding tasks. You can also invoke it explicitly with `/atelier`.

## What It Does

Atelier provides:

- **ReasonBlocks**: Proven procedures for specific domains (Shopify, PDP, tracker, etc.)
- **Rubrics**: Verification gates to ensure you didn't miss critical steps
- **Rescue procedures**: What to do when you hit repeated failures

## Commands

| Command             | What it does                      |
| ------------------- | --------------------------------- |
| `/atelier:status`   | Show current run state            |
| `/atelier:context`  | Show loaded ReasonBlocks + rubric |
| `/atelier:settings` | Show Atelier configuration        |

## MCP Tools

You have these tools via the `atelier` MCP server:

```python
# Before a task - get relevant ReasonBlock
atelier_get_reasoning_context(task="...", domain="...", tools=[...])

# Before executing a plan - check for dead ends
atelier_check_plan(task="...", domain="...", plan=[...])
# Returns: {"status": "passed" | "warn" | "blocked", "warnings": [...], "dead_ends": [...]}

# On repeated failure - get rescue procedure
atelier_rescue_failure(task="...", error="...", domain="...")

# After task - record the outcome
atelier_record_trace(task="...", status="success|failed", ...)

# For Shopify publish - verify against rubric
atelier_run_rubric_gate(rubric_id="rubric_shopify_publish", checks={...})
```

### V2 Memory tools [Atelier augmentation]

```python
# Store/retrieve named memory block
atelier_memory_upsert_block(agent_id="atelier:code", label="last_gid", value="gid://shopify/Product/12345")
atelier_memory_get_block(agent_id="atelier:code", label="last_gid")

# Archival memory — persist and recall
atelier_memory_archive(agent_id="atelier:code", text="...", source="run_123")
atelier_memory_recall(agent_id="atelier:code", query="Shopify GID pattern", top_k=5)

# Compact sleeptime memory to reduce context window
atelier_memory_summary(run_id="run_123")
```

### V2 Context-savings tools [Atelier augmentation]

```python
# Combined token-saving search + read (host-native tools remain the raw-access fallback)
atelier_search_read(query="publish_product function", path="src/")

# Deterministic batch edits (optional — host MultiEdit remains default)
atelier_batch_edit(edits=[{"path": "src/foo.py", "old_string": "...", "new_string": "..."}])

# Read-only SQL inspection
atelier_sql_inspect(connection_alias="default", sql="SELECT * FROM products LIMIT 5")

# Advise before host-native /compact — get preserve/reinject hints
atelier_compact_advise(run_id="run_123")
```

### V2 Lesson pipeline tools [Atelier augmentation]

```python
# Review pending lesson candidates
atelier_lesson_inbox(domain="beseam.shopify.publish", limit=10)

# Approve or reject a candidate (approved → ReasonBlock)
atelier_lesson_decide(lesson_id="les_001", decision="approve", reviewer="atelier:code", reason="...")
```

## Domains

| Domain                          | What it covers                                 |
| ------------------------------- | ---------------------------------------------- |
| `beseam.shopify.publish`        | Shopify product publishing, identity, rollback |
| `beseam.pdp.schema`             | PDP validation, structured data authority      |
| `beseam.catalog.fix`            | Catalog → PDP sync, ingest correctness         |
| `beseam.tracker.classification` | AI referral vs organic classification          |
| `beseam.audit_service_change`   | Audit service data changes                     |
| `coding`                        | General coding (failure loops, etc.)           |

## Example Usage

```
You: Update the product title for handle "winter-coat"
→ Call atelier_get_reasoning_context with domain=beseam.shopify.publish
→ Call atelier_check_plan before making the API call
→ Call atelier_run_rubric_gate after publish with checks
→ Call atelier_record_trace when done
```

## Verification

For critical tasks, always run the rubric gate:

- Shopify publish → `rubric_shopify_publish`
- PDP fix → `rubric_pdp_schema`
- Classification → `rubric_ai_referral_classification`

If any `block_if_missing` check fails, stop and fix before proceeding.
