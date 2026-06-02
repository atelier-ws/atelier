# Augment Code Parity Research

## Purpose

This note captures how current Atelier compares to the "smart assistant" qualities associated with Augment Code, and which parts of that parity should matter for the terminal-first reset.

## Existing Repo Research Already Present

Before this session, the repo already had Augment-focused planning material worth preserving:

- `docs/plans/context-quality-lift/grounding.md`
- `docs/plans/context-quality-lift/index.md`
- `docs/plans/context-quality-lift/M1-context-lineage.md`
- `docs/plans/context-quality-lift/M2-cache-aware-routing.md`
- `docs/plans/context-quality-lift/M3-counterexample-loop.md`
- `docs/plans/context-quality-lift/M4-scoped-pull-context.md`
- `docs/plans/world-class-atelier/00-deep-audit.md`
- `docs/plans/world-class-atelier/01-second-audit.md`

These docs already argue that Atelier's real frontier is not "copy Augment blindly," but to capture the context-quality levers that materially improve outcomes.

## What Augment Appears To Be Optimizing For

From public Augment material and prior internal repo research, the major themes are:

- whole-repo context retrieval and semantic indexing
- persistent/shared memory and context lineage
- agentic workflow orchestration
- strong codebase-aware assistance
- cost-aware routing and context selection
- polished developer UX around all of the above

## Where Atelier Already Has Meaningful Parity

### Repo Understanding And Context

- Atelier already composes context from reusable procedures, bootstrap summaries, and archival recall in runtime flows.
- Existing bootstrap/context machinery means Atelier is not starting from zero on repo understanding.

Relevant files:

- `src/atelier/core/runtime/engine.py`
- `src/atelier/core/service/bootstrap_context.py`

### Code Intelligence

- Atelier already has strong semantic/code-intel surfaces: symbols, node, callers, callees, usages, impact, pattern, and explore.
- This is already stronger than a generic search-first assistant and is one of the main things that should not regress.

Relevant files:

- `src/atelier/gateway/adapters/mcp_server.py`
- `src/atelier/core/capabilities/code_context/engine.py`

### Memory And Smart Recall

- Archival recall and semantic file memory already exist.
- Lesson promotion and recall-oriented capabilities are already part of the product shape, which overlaps with Augment's "smarter over time" story.

Relevant files:

- `src/atelier/core/capabilities/archival_recall/capability.py`
- `src/atelier/core/capabilities/semantic_file_memory/capability.py`
- `src/atelier/core/capabilities/lesson_promotion/`

### Host Integration And Workflow Help

- Claude/Codex/Copilot integrations, hooks, telemetry, and guardrails already exist.
- Atelier already has autopilot/workflow hints, even though they are not yet the same as a first-class workflow kernel.

Relevant files:

- `integrations/claude/plugin/hooks/session_start.py`
- `integrations/claude/plugin/hooks/hooks.json`
- `src/atelier/core/capabilities/autopilot/workflow_config.py`

### Areas Where Atelier May Already Be Ahead

- Loop detection / rescue
- Lesson promotion
- Vendor-neutral routing foundations
- Local-first architecture rather than cloud-only dependence

Relevant files:

- `src/atelier/core/capabilities/loop_detection/rescue.py`
- `src/atelier/core/capabilities/cross_vendor_routing/`

## Where Atelier Is Still Partial Or Behind

### Explicit Workflow Kernel

Atelier has workflow hints and routing/advisory state, but not yet the same explicit session-owned workflow object, task-local carry-forward state, and review boundary that make the execution loop feel truly "smart."

Relevant files:

- `src/atelier/core/capabilities/autopilot/workflow_config.py`
- `.planning/REQUIREMENTS.md`

### Real Routing Enforcement

Atelier still treats provider-enforced routing as future-only in the current execution contract, so routing is smarter as recommendation than as actual owned execution.

Relevant files:

- `src/atelier/core/capabilities/quality_router/execution_contract.py`

### Imported Session / Long-Horizon Project Memory

Some imported-session trace persistence is still TODO-backed, which means "project memory" parity is not yet complete for all history sources.

Relevant files:

- `src/atelier/core/service/ingest_session.py`
- `src/atelier/core/service/ingest_session_directory.py`

### Polyglot Semantic Depth

The strongest semantic/code-intel depth is still concentrated in Python / TypeScript / JavaScript. Broader language parity should not be treated as a solved problem yet.

Relevant files:

- `README.md`
- `src/atelier/core/capabilities/code_context/engine.py`

## What Should Matter For Milestone 1

These Augment-style parity goals should matter:

1. Better repo/context understanding in the live terminal loop
2. Explicit workflow state instead of prompt-only orchestration
3. Smarter routed execution on owned subcalls
4. Benchmark-backed quality proof for the "smartness" claims

These should not drive milestone 1:

1. Full cloud-hosted multi-tenant Augment parity
2. Deep IDE-native parity across every surface
3. Broad marketing-level "project brain" claims before the mechanisms are proven

## Implication For The Reset

The reset should not assume Atelier lacks Augment-like intelligence. The more accurate framing is:

- Atelier already has several of the smart-assistant building blocks.
- The main missing pieces are execution coherence, enforced routing, and benchmark-proofed outcome quality.
- Milestone 1 should close those gaps instead of chasing broad cloud/IDE parity.

## Sources

- `docs/plans/context-quality-lift/grounding.md`
- `docs/plans/world-class-atelier/00-deep-audit.md`
- `src/atelier/core/runtime/engine.py`
- `src/atelier/core/service/bootstrap_context.py`
- `src/atelier/gateway/adapters/mcp_server.py`
- `src/atelier/core/capabilities/archival_recall/capability.py`
- `src/atelier/core/capabilities/autopilot/workflow_config.py`
- `src/atelier/core/capabilities/quality_router/execution_contract.py`

---
*Augment parity research for Atelier reset*
*Researched: 2026-06-02*
