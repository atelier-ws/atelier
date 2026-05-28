# Phase 12: Cache-Aware Routing - Research

**Phase:** 12 — Cache-Aware Routing  
**Confidence:** HIGH for codebase/API findings; MEDIUM for exact heuristic constants.

## Summary

Phase 12 should extend the existing `ModelRouter` rather than introduce a parallel router. Current code exposes `ModelRouter.score(tool_name, task_text, session_state) -> ModelRecommendation | None`; docs call the new API `recommend()`, so implementation should add `recommend()` while keeping `score()` backward-compatible for all existing callers.

## Locked Constraints

- Compare `cache_eviction_cost_usd(prior_plan, current_plan, pricing)` against a deterministic `quality_gain_usd_estimated`.
- Preserve the prior route when cache eviction cost exceeds estimated quality gain.
- Add a default sticky window of 3 follow-up tool calls.
- Emit `route_decision` telemetry fail-open.
- Replace the M2 benchmark placeholder with deterministic local replay proof: >=10% cost reduction and zero quality-tier regressions.
- Do not add external dependencies.

## File-by-File Implementation Map

### Create

| File | Purpose |
|---|---|
| `src/atelier/core/capabilities/model_routing/cache_cost.py` | Pure `cache_eviction_cost_usd(plan_a, plan_b, pricing)` function. |
| `src/atelier/core/capabilities/model_routing/stickiness.py` | Sticky route state primitive, default window constant, decrement/reset helpers. |
| `tests/core/test_model_routing_cache_aware.py` | Focused tests for cache cost, stickiness, route decisions, telemetry, and serialization. |

### Modify

| File | Required changes |
|---|---|
| `src/atelier/core/capabilities/model_routing/router.py` | Add `recommend()`; extend `ModelRecommendation` with cache-aware fields; keep `score()` positional API unchanged. |
| `src/atelier/core/capabilities/model_routing/__init__.py` | Export cache-cost and stickiness helpers. |
| `src/atelier/gateway/adapters/mcp_server.py` | In fallback recommendation path, call/use the new route-decision telemetry payload while preserving existing `model_recommendation` behavior. |
| `tests/core/test_model_router.py` | Keep existing regression tests green. |
| `tests/benchmarks/context_quality/M2_routing.py` | Replace skip placeholder with deterministic replay benchmark. |

## Existing APIs to Reuse

- `ModelRecommendation` currently has `tier`, `model`, `route_tier`, `reasons`, `score`, `cache_affinity_model`, and `to_dict()`. Extend it rather than creating `RouteRecommendation`.
- `PrefixCachePlan` exposes `prefix_hash`, `prefix_tokens`, `dynamic_tokens`, `total_tokens`, and `invalidated_reason`.
- `ModelPricing` exposes `input`, `cache_read`, `cache_write`, `cost_usd()`, and `tokens_to_usd()`.
- `RunLedger.record(kind, summary, payload)` can persist `kind="route_decision"` events.

## Recommended Router Flow

1. Preserve bench-off behavior: if bench mode is off, return `None`.
2. Compute baseline route using existing scoring logic.
3. If `stickiness_remaining > 0` and `prior_route` exists, preserve prior route with `decision="sticky_window"` and decrement remaining stickiness.
4. If `prior_plan`, `current_plan`, and `prior_route` exist:
   - compute cache eviction cost,
   - compute deterministic quality gain,
   - if cache cost is greater, preserve prior route with `decision="cache_preserve"`.
5. Otherwise return baseline with `sticky_until_tool_calls=3`.
6. Emit telemetry through an optional sink or ledger; swallow sink exceptions.

## Cache Cost Function

Recommended behavior:

- Same `prefix_hash` -> `0.0`.
- Prefix changed and `pricing.cache_write > 0` -> `tokens_to_usd(max(prefix_tokens), "cache_write")`.
- If cache-write pricing is unknown but input pricing exists -> input-token fallback.
- If pricing is unknown -> finite conservative fallback; do not use infinity in telemetry.

## Quality-Gain Estimate

Use a deterministic static table by tier rank. Suggested order:

`cheap=0`, `medium=1`, `expensive=2`

Only positive upward moves have non-zero quality gain. Keep constants small enough that large prefix invalidations preserve cache, but allow high-value frontier moves to win when cache cost is tiny.

## Test Architecture

Add `tests/core/test_model_routing_cache_aware.py` with at least:

- `test_cache_eviction_cost_zero_when_prefix_hash_same`
- `test_cache_eviction_cost_uses_cache_write_rate_when_prefix_changes`
- `test_cache_eviction_cost_falls_back_to_input_rate_when_cache_write_unknown`
- `test_cache_eviction_cost_biases_sticky_when_pricing_unknown`
- `test_recommend_backward_compatible_without_cache_inputs`
- `test_stickiness_holds_prior_route_for_window`
- `test_stickiness_zero_allows_baseline_scoring`
- `test_cache_cost_beats_quality_gain_preserves_prior_route`
- `test_quality_gain_beats_cache_cost_switches_to_baseline`
- `test_route_decision_sink_called_for_cache_aware_recommend`
- `test_route_decision_sink_failure_is_swallowed`
- `test_to_dict_includes_cache_aware_fields`

## Benchmark Architecture

Replace `tests/benchmarks/context_quality/M2_routing.py` placeholder with a slow deterministic replay benchmark:

- 50 synthetic traces.
- Each trace has tool name, task text, prior/baseline tier expectation, prefix token count, invalidation flag, and quality-gain estimate.
- Compare baseline estimated cost vs cache-aware cost.
- Assert `cost_reduction >= 0.10`.
- Assert `quality_tier_regressions == 0`.

## Common Pitfalls

- Do not make `score()` keyword-only or otherwise break positional callers.
- Do not introduce a separate `RouteRecommendation`; existing code uses `ModelRecommendation`.
- Do not let telemetry failures affect routing.
- Do not use `float("inf")` in JSON telemetry.
- Benchmark must test both cost reduction and no quality-tier regression.

## Validation Architecture

Quick:

```bash
uv run pytest tests/core/test_model_router.py tests/core/test_model_routing_cache_aware.py -q
uv run pytest tests/benchmarks/context_quality/M2_routing.py -m slow -q
```

Static:

```bash
uv run ruff check src/atelier/core/capabilities/model_routing tests/core/test_model_routing_cache_aware.py tests/benchmarks/context_quality/M2_routing.py
uv run mypy src/atelier/core/capabilities/model_routing
```

Full phase gate:

```bash
make lint && make typecheck && make test
```

Known baseline note: repository typecheck may report the pre-existing `src/atelier/core/capabilities/sync/encryption.py` `no-any-return` error if it has not been fixed elsewhere.

## Sources

- `.planning/phases/12-cache-aware-routing/12-CONTEXT.md`
- `.planning/PROJECT.md`
- `.planning/REQUIREMENTS.md`
- `.planning/ROADMAP.md`
- `docs/plans/context-quality-lift/M2-cache-aware-routing.md`
- `src/atelier/core/capabilities/model_routing/router.py`
- `src/atelier/core/capabilities/prefix_cache/planner.py`
- `src/atelier/core/capabilities/pricing.py`
- `src/atelier/infra/runtime/run_ledger.py`
- `tests/core/test_model_router.py`
- `tests/benchmarks/context_quality/M2_routing.py`
