# Phase 3: Routed Execution MVP - Context

**Gathered:** 2026-06-03
**Status:** Ready for planning

<domain>
## Phase Boundary

As a terminal coding agent user, I want Atelier-owned subcalls to run through an explicit provider/model I choose or an auto-selected route, while preserving prompt-cache locality, so that I can control important runs and still let policy choose when appropriate.

Success criteria carried from ROADMAP.md:
1. User can execute Atelier-owned subcalls through enforced provider/model routing rather than advisory-only routing.
2. User can explicitly select provider and model as a first-class route mode for owned subcalls and benchmarks.
3. User can choose `auto` mode when they want policy to select from task class, provider health, quality risk, price, latency, and cache warmth.
4. User can preserve provider-side prompt-cache affinity across explore -> plan -> review -> execute loops when the selected or auto route is cache-compatible.
5. User can inspect actual provider/model/cache provenance for each routed subcall.
6. User can keep the top-level host conversation native while routed execution runs safely on owned subcalls.
7. User can shadow a Claude-Code-compatible local router bridge before opting into broader host-level routing.

Requirements in scope:
- ROUT-01
- ROUT-02
- ROUT-03
- ROUT-04
- ROUT-05
- ROUT-06
- ROUT-07

</domain>

<decisions>
## Implementation Decisions

### Fixed Direction

- Start with explicit provider/model selection as a first-class route mode. Add `auto` as another first-class route mode, not a hidden override.
- Preserve prompt-cache locality as a first-class route signal. A warm cache route should usually beat a slightly cheaper cold route.
- Keep enforced routing on Atelier-owned subcalls first. Top-level host routing starts as a shadow-safe bridge with explicit opt-in enforcement after measured parity.
- Use the existing `model_routing`, `cross_vendor_routing`, `prefix_cache`, `prompt_compilation`, `swarm`, tracing, and ledger foundations before adding new abstractions.
- Treat the installed WOZ plugin as evidence for the local-router pattern, not as code to copy. The useful concepts are preset paths, provider bindings, model mappings, request modifications, and host-env/base-url control.

</decisions>

<code_context>
## Existing Code Insights

- `src/atelier/core/capabilities/model_routing/router.py` is currently advisory and already mentions host CLIs owning actual model selection.
- `src/atelier/core/capabilities/model_routing/cache_cost.py` and `stickiness.py` already model cache eviction economics and caller-owned sticky state.
- `src/atelier/core/capabilities/prefix_cache/` already contains prompt-cache planning primitives.
- `src/atelier/core/capabilities/cross_vendor_routing/` already has vendor/model ranking concepts.
- `src/atelier/core/capabilities/swarm/` already has provider-backed worker concepts for `openai` and `litellm`.
- `src/atelier/infra/internal_llm/` and LiteLLM support should be reused where production provider calls are needed.
- `src/atelier/infra/runtime/run_ledger.py` and reporting surfaces should record real provider/model/cache provenance.

</code_context>

<specifics>
## Specific Ideas

- Add explicit route selection for provider/model plus an `auto` route policy that scores task class, required tool use, quality risk, context size, latency, provider health, price, prior failures, and cache warmth.
- Maintain a provider catalog with capabilities, transport shape, model mappings, cache support, prompt-cache pricing, max context, tool-use support, and fallback priority.
- Add owned execution lanes for route-selected provider calls with deterministic provenance artifacts.
- Add prompt-cache affinity state per workflow/session: cache key, provider/model, static-prefix hash, last cache write/read tokens, miss reason, and eviction cost.
- Prefer warm-route stickiness across explore -> plan -> review -> execute loops unless the route is unhealthy, lacks required capability, breaches quality threshold, or has measured worse cost.
- Add a local host router bridge that can expose Claude-Code-compatible preset paths such as `/router-preset/claudecode/...`, first in shadow mode and later as an explicit opt-in.
- Record both modeled and actual wire usage where available. Never claim cache savings without usage evidence or an explicit modeled label.

</specifics>

<deferred>
## Deferred Ideas

- Making host-level local-router enforcement the default for all top-level chat.
- Broad provider-marketplace UX.
- Provider-specific prompt rewrites that are not needed for benchmark proof.

</deferred>
