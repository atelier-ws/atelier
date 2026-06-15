# Feature-flag rollout tracker

Tracks the gated (opt-in / kill-switchable) capabilities so they can be enabled,
tested, and measured one at a time.

> **State note:** the `parity-closure` -> `bench` merge is **applied** (merge commit
> `d828e5ca`). This branch (`feat/token-efficiency-additions`) builds on it with the
> additional token-efficiency features (T3/T5/T9-T12) and review-hardening flags listed
> below. Group A + these additions are all present on this branch; Group B was already
> in `bench`.

Legend: status = `[ ]` not started / `[~]` enabled+testing / `[x]` rolled out (default flipped or accepted).

---

## Group A - parity-closure token-efficiency features (require the merge first)

### Default-OFF (flip on to test). Verified flags from `git show parity-closure:...`

| St | Feature (WS) | Flag (verbatim) | Default | Enable | What to test / measure |
|----|--------------|-----------------|---------|--------|------------------------|
| [ ] | Complexity-tier model routing (WS6/N1) | `ATELIER_TIER_ROUTING` env, or `session_state["tier_routing"]` | OFF | `ATELIER_TIER_ROUTING=1` | Cost + quality on a hard-task set; confirm hard work is never downgraded (router uses `max(baseline, complexity)`). Gate: `model_routing/router.py::_apply_complexity_tier`. |
| [ ] | Edit-loop correctness gate (WS1) | `ATELIER_EDIT_VERIFY` env, or `verify=True` per edit call | OFF | `ATELIER_EDIT_VERIFY=1` | False-rollback rate + per-edit latency vs. retry-burn saved. Fail-open. Gate: `verification/edit_gate.py::run_edit_gate`, wired in `mcp_server.py`. |
| [ ] | Compact output encoding (WS3/G13/N7) | `format=compact` arg on read/search (default `auto`) | OFF (`auto`) | pass `format=compact` | Per-tool token savings via the ledger; confirm consumers parse columnar form. Never inflates (N6 gate, >=15%). |
| [ ] | Tool-output spill (T7) | `ATELIER_TOOL_OUTPUT_SPILL` env | OFF (`0`) | `ATELIER_TOOL_OUTPUT_SPILL=1` | Overflow of shell/sql/read/web_fetch results is spilled (full payload to the spill dir) + a summary + ref id + retrieve hint, instead of being discarded by the byte ceiling. Recover via `compact` tool `op="retrieve"`. Spill dir = `ATELIER_MCP_SPILL_DIR` (shared with native_search). Gate: `mcp_server.py::_spill_oversized_result_text`, `tool_supervision/tool_output_spill.py`. |
| [ ] | Reversible auto-compaction (T8) | `ATELIER_AUTO_COMPACT_OUTPUT` env | OFF (`0`) | `ATELIER_AUTO_COMPACT_OUTPUT=1` | Oversized assembly-path results are auto-compacted (AST-aware via source_projection for code, else compact_output.compact). REVERSIBLE: the untransformed original is written to the T7 spill store and recoverable via `compact` `op="retrieve"`. Threshold reuses `ATELIER_MCP_COMPACT_RESULT_CHARS`. Gate: `mcp_server.py::_auto_compact_result_text`. |
| [ ] | Autonomous-compaction lever (T6) | none (agent-callable `compact` tool `op="consolidate"`) | n/a (op default `"compact"` = current behavior) | call `compact` with `op="consolidate"` | Agent distills recent findings + prunes stale history on demand, reusing the existing compaction entrypoint (`ContextCompressor().compress` via `_compress_context`). Gate: `mcp_server.py::tool_compact`. |
| [ ] | History-compaction trigger (T5) | `ATELIER_AUTO_COMPACT` env | OFF (`0`) | `ATELIER_AUTO_COMPACT=1` | Gates the (previously unconditional) `summarize_memory` compress on live context fill >= `policy.trigger_at_context_fraction`. Fail-open. Gate: `core/runtime/engine.py::_should_auto_compact`/`_live_context_fill`, `optimization/policy.py::should_compact`. |
| [ ] | Learned model routing (T9) | `ATELIER_LEARNED_ROUTING` env (+ `_THRESHOLD` def 0.9, `_MIN_SAMPLES` def 20) | OFF (`0`) | `ATELIER_LEARNED_ROUTING=1` | Gates the heuristic tier step-down on a calibrated P(weak succeeds) over logged `verify_route`/ab_calibration outcomes; None/below-threshold holds baseline (safety floor preserved). Gate: `model_routing/success_predictor.py`, `router.py::_apply_complexity_tier`. |
| [ ] | Perplexity/entropy compression (T10/T11) | `ATELIER_PERPLEXITY_COMPRESSION` env | OFF (`0`) | `ATELIER_PERPLEXITY_COMPRESSION=1` | Feeds perplexity/entropy utilities into the budget knapsack + token-level pruning; headless structural-entropy fallback when `ATELIER_LLM_BACKEND=none`. Gate: `code_context/ppl_rank.py`, `context_compression/perplexity_pruning.py`, `infra/internal_llm/logprobs.py`. |
| [ ] | Goal-conditioned line skimmer (T12) | `ATELIER_LINE_SKIM` env | OFF (`0`) | `ATELIER_LINE_SKIM=1` | Prunes scoped-context chunks to goal-relevant lines (keeps structural anchors); reuses the reranker with lexical fallback. Gate: `scoped_context/line_skimmer.py`, `pull.py`. |
| [ ] | HTTP project-override (review H1, security) | `ATELIER_HTTP_ALLOW_PROJECT_OVERRIDE` env | OFF (`0`) | `ATELIER_HTTP_ALLOW_PROJECT_OVERRIDE=1` | Allows a wire-supplied `project_path` override, CONFINED to the workspace root; default off rejects out-of-root pivots. Gate: `mcp_server.py::_set_request_project`. |

### Default-ON (shipped; rollout = "verify, has kill switch")

| St | Feature (WS) | Flag | Default | Disable | Notes |
|----|--------------|------|---------|---------|-------|
| [x] | Per-tool token ledger (N4) | none (additive) | ON | n/a | Measurement backbone. Read via the savings summary. Turn this on FIRST to judge everything else. |
| [x] | Savings gate (N6) | none | ON | n/a | Only engages under `format=compact`; cannot inflate. |
| [x] | Warm stdio code-index (G10) | `ATELIER_SERVICE_CODE_WARM` | ON (`1`) | `0`/`false`/`no`/`off` | `service/code_warm.py`. |
| [x] | Repo-map tag cache (T3) | `ATELIER_REPOMAP_TAG_CACHE` | ON (`1`) | `0`/`false`/`off`/`no` | Persistent mtime+size-keyed SQLite tag cache; warm starts skip full-repo re-parse. Correctness-preserving via invalidation; in-memory fallback on DB error. Gate: `repo_map/tag_cache.py`, `graph.py::build_reference_graph`. |
| [x] | MCP HTTP body cap (review H2, security) | `ATELIER_MCP_HTTP_MAX_BODY_BYTES` | ON (`4194304`) | (byte count) | Caps `POST /mcp` request body (413 over the limit); dispatch runs via threadpool so a slow tool can't block the event loop. Gate: `mcp_http.py`. |

### Review-hardening fixes (unconditional — no flag, always on)

_From the adversarial review of `a1f63f54..tip`; security/correctness fixes that are not gated._

| Fix | What | Where |
|-----|------|-------|
| C1 (security) | `POST/GET /mcp` now require `_require_auth` (was an unauthenticated tool surface) | `gateway/adapters/mcp_http.py`, `openai_gateway/app.py` |
| H3 | per-tool token-ledger RMW now locked (no lost updates under the 16-worker dispatch) | `core/capabilities/tool_token_ledger.py` |
| H4 | ast-grep subprocess timeout -> domain error; default scan no longer walks `.git` | `infra/code_intel/astgrep/adapter.py` |
| M4 (security) | redaction no longer leaks multi-word secret values (`\S+` -> `\S[^\r\n]*`) | `core/foundation/redaction.py` |
| M2 | gateway returns a correlation-id error instead of raw `str(exc)` | `gateway/adapters/mcp_http.py` |

---

## Group B - already in `bench` (env-gated)

### Default-OFF

| St | Feature | Flag | Default | Enable | Test / measure |
|----|---------|------|---------|--------|----------------|
| [ ] | Vector / ANN retrieval (WS2/WS7) | `ATELIER_VECTOR_SEARCH_ENABLED` | OFF (`false`) | `1`/`true`/`yes` | Retrieval recall/precision; uses `WEIGHTS_WITH_VECTOR` when on. `storage/vector.py::is_vector_enabled`. |
| [ ] | Internal LLM backend | `ATELIER_LLM_BACKEND` | OFF (`none`) | `ollama`/`openai`/`litellm` | Summary/recall quality + cost. |
| [ ] | Langfuse tool telemetry | `ATELIER_LANGFUSE_ENABLED` | OFF | `1` | Trace completeness. |
| [ ] | Host-router enforcement bridge | `ATELIER_HOST_ROUTER_ENABLE` | OFF | `1` | Route enforcement vs. host. |
| [ ] | Background service API | `ATELIER_SERVICE_ENABLED` | OFF | `1` | (+ `ATELIER_REQUIRE_AUTH`, `ATELIER_SERVICE_HOST/_PORT`). |
| [ ] | MCP auto-update | `ATELIER_AUTO_UPDATE` | OFF (`0`) | `1` | Opt-in self-update. |

### Default-ON (kill switches)

| St | Feature | Flag | Default | Disable |
|----|---------|------|---------|---------|
| [x] | Read/search result compaction | `ATELIER_MCP_COMPACT_RESULT_CHARS` | ON (`262144`) | `0` |
| [x] | Result byte ceiling | `ATELIER_MCP_MAX_RESULT_BYTES` | ON (`6291456`) | (byte count) |
| [x] | Code index autosync | `ATELIER_CODE_AUTOSYNC` | ON (`1`) | `0` |
| [x] | Code-intel savings credit | `ATELIER_CODE_INTEL_CREDIT` | ON (`1`) | `0` |
| [x] | Read baseline dedup | `ATELIER_READ_BASELINE_DEDUP` | ON (`1`) | `0` |
| [x] | Context dedup compaction | `ATELIER_CONTEXT_DEDUP` | ON (`1`) | `0` |
| [x] | Code reranker | `ATELIER_CODE_RERANKER_ENABLED` | ON | (needs a model) |
| [x] | Git-lineage scoring | `ATELIER_LINEAGE_DISABLED` | ON | `1` (kill) |
| [x] | Internal-LLM response cache | `ATELIER_INTERNAL_LLM_CACHE` | ON (`1`) | `0` |

---

## How to use this tracker

1. Re-apply the parity-closure merge (Group A only becomes testable after that).
2. Turn the **N4 ledger** on first (it is the measurement backbone).
3. Flip ONE Group-A default-off flag, run the relevant benchmark, record the
   token/cost/quality delta, then set its status `[~]` -> `[x]` (or revert).
4. Recommended order (lowest risk -> highest): compact `format` -> edit gate -> tier routing.

Verification commands per flag, e.g.:
```bash
ATELIER_EDIT_VERIFY=1 uv run pytest tests/... 
ATELIER_TIER_ROUTING=1 uv run atelier ...   # then compare ledger / route decisions
```
