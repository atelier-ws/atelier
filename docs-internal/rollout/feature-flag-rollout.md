# Feature-flag rollout tracker

Tracks the gated (opt-in / kill-switchable) capabilities so they can be enabled,
tested, and measured one at a time.

> **State note (update as you go):** the `parity-closure` -> `bench` merge was
> **reset/undone** (reflog `HEAD@{0}: reset`). Group A features live on the
> `parity-closure` branch and are **NOT in `bench`** until that merge is re-applied.
> Group B features are already in `bench` today.

Legend: status = `[ ]` not started / `[~]` enabled+testing / `[x]` rolled out (default flipped or accepted).

---

## Group A - parity-closure token-efficiency features (require the merge first)

### Default-OFF (flip on to test). Verified flags from `git show parity-closure:...`

| St | Feature (WS) | Flag (verbatim) | Default | Enable | What to test / measure |
|----|--------------|-----------------|---------|--------|------------------------|
| [ ] | Complexity-tier model routing (WS6/N1) | `ATELIER_TIER_ROUTING` env, or `session_state["tier_routing"]` | OFF | `ATELIER_TIER_ROUTING=1` | Cost + quality on a hard-task set; confirm hard work is never downgraded (router uses `max(baseline, complexity)`). Gate: `model_routing/router.py::_apply_complexity_tier`. |
| [ ] | Edit-loop correctness gate (WS1) | `ATELIER_EDIT_VERIFY` env, or `verify=True` per edit call | OFF | `ATELIER_EDIT_VERIFY=1` | False-rollback rate + per-edit latency vs. retry-burn saved. Fail-open. Gate: `verification/edit_gate.py::run_edit_gate`, wired in `mcp_server.py`. |
| [ ] | Compact output encoding (WS3/G13/N7) | `format=compact` arg on read/search (default `auto`) | OFF (`auto`) | pass `format=compact` | Per-tool token savings via the ledger; confirm consumers parse columnar form. Never inflates (N6 gate, >=15%). |

### Default-ON (shipped; rollout = "verify, has kill switch")

| St | Feature (WS) | Flag | Default | Disable | Notes |
|----|--------------|------|---------|---------|-------|
| [x] | Per-tool token ledger (N4) | none (additive) | ON | n/a | Measurement backbone. Read via the savings summary. Turn this on FIRST to judge everything else. |
| [x] | Savings gate (N6) | none | ON | n/a | Only engages under `format=compact`; cannot inflate. |
| [x] | Warm stdio code-index (G10) | `ATELIER_SERVICE_CODE_WARM` | ON (`1`) | `0`/`false`/`no`/`off` | `service/code_warm.py`. |

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
