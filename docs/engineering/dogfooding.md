# Dogfooding

Atelier is dogfooded against itself and against the Beseam Shopify publish workflow. This document describes the verified scenarios and how to run them.

## Verified Scenarios

### Scenario 1: Dead-End Plan Detection (Shopify Publish)

**Setup:** Agent proposes a plan using `product handle` (a known dead end) instead of `product GID`.

**Test:**

```bash
uv run atelier check-plan \
    --task "Publish Shopify product" \
    --domain beseam.shopify.publish \
    --step "Parse product handle from PDP URL" \
    --step "Use handle to update metafields" \
    --json
```

**Expected:**

```json
&#123;
  "status": "blocked",
  "exit": 2,
  "warnings": [
    "dead end: product handle from pdp",
    "dead end: lookup product by handle"
  ]
&#125;
```

### Scenario 2: GID-Based Plan Passes

**Test:**

```bash
uv run atelier check-plan \
    --task "Publish Shopify product" \
    --domain beseam.shopify.publish \
    --step "Fetch product by GID via GraphQL" \
    --step "Snapshot current state before changes" \
    --step "Update metafields using product GID" \
    --step "Re-fetch product and run post-publish audit" \
    --json
```

**Expected:** `&#123;"status": "pass", "exit": 0&#125;`

### Scenario 3: Rubric Gate — Full Pass

**Test:**

```bash
echo '&#123;
  "product_identity_uses_gid": true,
  "pre_publish_snapshot_exists": true,
  "write_result_checked": true,
  "post_publish_refetch_done": true,
  "post_publish_audit_passed": true,
  "rollback_available": true,
  "localized_url_test_passed": true,
  "changed_handle_test_passed": true
&#125;' | uv run atelier run-rubric rubric_shopify_publish --json
```

**Expected:** `&#123;"status": "pass"&#125;`

### Scenario 4: Rubric Gate — Blocked (Missing Checks)

**Test:**

```bash
echo '&#123;
  "product_identity_uses_gid": true,
  "pre_publish_snapshot_exists": false
&#125;' | uv run atelier run-rubric rubric_shopify_publish --json
```

**Expected:** `&#123;"status": "blocked", "failed_checks": ["pre_publish_snapshot_exists", ...]&#125;`

### Scenario 5: Trace Record

```bash
echo '&#123;
  "agent": "claude-code",
  "domain": "beseam.shopify.publish",
  "task": "Dogfood: Publish product GID 123",
  "status": "success",
  "commands_run": ["shopify.get_product", "shopify.update_metafield", "shopify.get_product"],
  "errors_seen": [],
  "diff_summary": "Updated metafields for gid://shopify/Product/123",
  "output_summary": "Product published, audit passed"
&#125;' | uv run atelier record-trace --json
```

**Expected:** `&#123;"id": "trace_<hash>"&#125;` with exit 0.

### Scenario 6: Extract Block from Trace

```bash
TRACE_ID=$(uv run atelier trace list --json | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
uv run atelier extract-block "$TRACE_ID" --json
```

**Expected:** A candidate block with `confidence > 0` and `reasons` list.

### Scenario 7: Repeated Pytest Loop Rescue

**Task:** failing pytest loop, same signature repeated.

```bash
uv run atelier rescue \
  --task "Fix repeated pytest failure" \
  --error "AssertionError: expected 200 got 500" \
  --domain "beseam.testing" \
  --json
```

**Expected:** rescue output contains a procedural sequence and matched block IDs.

### Scenario 8: Failure Cluster Analysis → ReasonBlock Proposal

```bash
curl -s -X POST http://127.0.0.1:8787/v1/failures/analyze \
  -H "Authorization: Bearer $&#123;ATELIER_API_KEY&#125;" \
  -H "Content-Type: application/json" \
  -d '&#123;"limit": 100&#125;'
```

**Expected:** one or more clusters with fingerprints and suggested procedural guidance fields.

### Scenario 9: Eval Generated from Cluster

```bash
LOCAL=1 uv run python -m pytest tests/test_swe_benchmark_harness.py -q
```

**Expected:** benchmark/eval harness generates valid run + evaluation artifacts for configured cases.

### Scenario 10: Pack Install + Benchmark

```bash
uv run atelier --root .atelier pack install src/atelier/packs/official/atelier-pack-coding-general --json
uv run atelier --root .atelier benchmark-packs --json
```

**Expected:** install succeeds and benchmark reports baseline vs host+core vs host+core+pack metrics.

## Running the Full Dogfood Suite

```bash
cd atelier && make verify
# 209 passed, 9 skipped — skips are Postgres-gated and expected
```

The pytest suite in `tests/test_golden_fixtures.py` covers all the above scenarios programmatically.

## `rubric_shopify_publish` Checks Reference

The 8 required checks for the Shopify publish rubric (as of last dogfood):

| Check                         | Description                               |
| ----------------------------- | ----------------------------------------- |
| `product_identity_uses_gid`   | Product identified by GID, not handle     |
| `pre_publish_snapshot_exists` | State snapshot taken before changes       |
| `write_result_checked`        | API write response was checked for errors |
| `post_publish_refetch_done`   | Product re-fetched after publish          |
| `post_publish_audit_passed`   | Post-publish audit succeeded              |
| `rollback_available`          | Rollback procedure exists                 |
| `localized_url_test_passed`   | Localized URL test ran                    |
| `changed_handle_test_passed`  | Changed-handle test ran                   |

## Dogfood Results Log

See `AGENT_README.md` → Dogfooding Scorecard section for the latest pass/fail record.
