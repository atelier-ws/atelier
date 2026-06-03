# Phase 2: Execution Kernel MVP - Research

**Researched:** 2026-06-03  
**Domain:** execution workflow state, session continuity, tracing/reporting reuse, benchmark-only grounded edit enforcement  
**Confidence:** MEDIUM

## User Constraints (from CONTEXT.md)

### Locked Decisions / Fixed Direction
- Reuse Atelier's existing runtime, tracing, and reporting foundations instead of inventing a parallel workflow engine. [CITED: `.planning/phases/02-execution-kernel-mvp/02-CONTEXT.md:34-38`]
- Build explicit workflow state and carry-forward outputs on top of the newly shipped Search-first path. [CITED: `.planning/phases/02-execution-kernel-mvp/02-CONTEXT.md:34-38`]
- Convert Phase 1's soft grounded-loop guidance into benchmark-path edit discipline without bloating normal flows. [CITED: `.planning/phases/02-execution-kernel-mvp/02-CONTEXT.md:34-38`]
- Prefer correct implementation over heavy verification loops. [CITED: `.planning/phases/02-execution-kernel-mvp/02-CONTEXT.md:34-38`]

### the agent's Discretion
- All implementation choices are at the agent's discretion unless a genuine blocker appears. Optimize for the benchmark-first terminal coding agent target: Eval is the execution-discipline reference, Augment is the context-quality reference, and WOZ remains the ergonomics reference already established in Phase 1. [CITED: `.planning/phases/02-execution-kernel-mvp/02-CONTEXT.md:31-32`]

### Deferred Ideas (OUT OF SCOPE)
- Broader provider routing changes (Phase 3) [CITED: `.planning/phases/02-execution-kernel-mvp/02-CONTEXT.md:67-73`]
- Benchmark protocol and proof surfaces (Phase 4) [CITED: `.planning/phases/02-execution-kernel-mvp/02-CONTEXT.md:67-73`]
- Any cloud-style Augment parity beyond what directly improves the terminal loop [CITED: `.planning/phases/02-execution-kernel-mvp/02-CONTEXT.md:67-73`]

## Project Constraints (from copilot-instructions.md / AGENTS.md / CLAUDE.md)

- Keep gateway entrypoints thin; new behavior belongs in `core/capabilities/`, not `mcp_server.py` or CLI command bodies. [CITED: `copilot-instructions.md:10-18`] [CITED: `CLAUDE.md` excerpt in prompt]
- Prefer Atelier MCP tools/surfaces over host-native alternatives; use native fallbacks only when Atelier is unavailable. [CITED: `copilot-instructions.md:10-18`]
- Use symbols/callers/usages before raw text search when code relationships matter. [CITED: `copilot-instructions.md:10-18`]
- All Python commands must use `uv run`. [CITED: `CLAUDE.md` excerpt in prompt]
- Make surgical brownfield changes; do not invent speculative abstractions or parallel systems. [CITED: `AGENTS.md` excerpt in prompt] [CITED: `copilot-instructions.md:10-18`]
- Generated instruction files are not source-of-truth; do not hand-edit generated host artifacts. [CITED: `CLAUDE.md` excerpt in prompt]

## Summary

Atelier already has most of the substrate for Phase 2, but it is split across three places: a typed `WorkflowState` persisted in workspace `session_state.json`, durable `RunLedger`/`Trace` persistence, and hook-driven `session_stats`/dashboard reporting. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:56-174`] [CITED: `src/atelier/core/capabilities/autopilot/factory.py:191-222`] [CITED: `src/atelier/infra/runtime/run_ledger.py:392-439`] [CITED: `src/atelier/core/capabilities/plugin_runtime.py:1211-1268`]

The smallest brownfield implementation is to **extend the existing workflow state already owned by `core/capabilities/autopilot`**, persist additional task-local execution data in the same workspace `session_state.json`, mirror user-visible plan/progress/workflow events into `RunLedger`, and surface them through the existing trace/session-report/dashboard/statusline paths. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:76-174`] [CITED: `src/atelier/gateway/adapters/mcp_server.py:5273-5678`] [CITED: `src/atelier/core/capabilities/plugin_runtime.py:1536-1577`] [CITED: `src/atelier/infra/runtime/session_report.py:162-203`]

**Primary recommendation:** Reuse `WorkflowState + session_state.json + RunLedger`; add benchmark-only edit gating at the MCP edit path and host pre-edit hook, keyed off existing benchmark mode/env rather than a new workflow engine. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:56-174`] [CITED: `integrations/claude/plugin/hooks/pre_tool_use.py:62-90`] [CITED: `src/atelier/bench/mode.py:24-61`] [ASSUMED]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Explicit workflow state (`explore/plan/execute/review`) | API / Backend | Database / Storage | Canonical typed state already lives in core logic and is persisted to workspace state. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:56-174`] |
| Plan approval / revision / rerun | API / Backend | Gateway / Host adapter | No current MCP surface mutates plan state; gateway will need a thin wrapper over core-owned state updates. [CITED: `src/atelier/infra/runtime/run_ledger.py:44-74`] [CITED: `src/atelier/gateway/adapters/mcp_server.py:1042-2862`] |
| Resume with current task + outputs | Database / Storage | API / Backend | Workspace `session_state.json` is the live mutable store; checkpoints/handover are durable helpers. [CITED: `src/atelier/core/capabilities/autopilot/factory.py:191-222`] [CITED: `src/atelier/infra/runtime/checkpoint.py:37-170`] [CITED: `src/atelier/infra/runtime/context_compressor.py:119-181`] |
| Workflow event / progress surfacing | API / Backend | Database / Storage | `RunLedger`, `trace`, `session_stats`, session report, and dashboard already exist. [CITED: `src/atelier/infra/runtime/run_ledger.py:103-189`] [CITED: `src/atelier/gateway/adapters/mcp_server.py:1644-1962`] [CITED: `src/atelier/core/capabilities/plugin_runtime.py:1211-1577`] |
| Grounded edit gate on benchmark path | Gateway / Host adapter | API / Backend | MCP `tools/call` and Claude `pre_tool_use` are the narrow interception points before edits land. [CITED: `src/atelier/gateway/adapters/mcp_server.py:5712-5855`] [CITED: `integrations/claude/plugin/hooks/pre_tool_use.py:62-90`] |

## Phase Requirements

| ID | Description | Research Support |
|---|---|---|
| EXEC-01 | explicit explore/plan/execute/review states | Extend existing `WorkflowState`; add `review` and persist it in workspace state. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:76-174`] |
| EXEC-02 | approve/revise/re-run a plan before execution | Reuse `RunLedger.current_plan`, add a thin live-state mutation/read surface; no current MCP tool exposes this. [CITED: `src/atelier/infra/runtime/run_ledger.py:44-74`] [CITED: `src/atelier/gateway/adapters/mcp_server.py:1042-2862`] |
| EXEC-03 | resume execution with current task state and prior outputs preserved | Store live task outputs in workspace `session_state.json`; optionally snapshot compact summaries into checkpoints/handover. [CITED: `src/atelier/core/capabilities/autopilot/factory.py:191-222`] [CITED: `src/atelier/infra/runtime/checkpoint.py:37-90`] [CITED: `src/atelier/infra/runtime/context_compressor.py:119-181`] |
| EXEC-04 | inspect workflow events and task progress | Emit workflow/progress into `RunLedger` and existing stats/reporting surfaces. [CITED: `src/atelier/infra/runtime/run_ledger.py:103-189`] [CITED: `src/atelier/core/capabilities/plugin_runtime.py:1211-1577`] |
| EXEC-05 | benchmark-path edits require prior grounding | Add a hard benchmark-only gate before edit execution; use recent read/search/code-intel evidence, not prompt text alone. [CITED: `src/atelier/gateway/adapters/mcp_server.py:5712-5855`] [CITED: `integrations/claude/plugin/hooks/pre_tool_use.py:62-90`] [CITED: `src/atelier/bench/mode.py:24-61`] |
| INTL-03 | keep current tracing/reporting/host-enforcement surfaces | Reuse trace/session report/dashboard/session_stats/hooks instead of a parallel workflow log. [CITED: `src/atelier/gateway/adapters/mcp_server.py:1644-1962`] [CITED: `src/atelier/core/capabilities/plugin_runtime.py:1211-1577`] [CITED: `src/atelier/core/service/api.py:3792-4190`] |

## Standard Stack

### Core

| Library / Module | Version | Purpose | Why Standard |
|---|---|---|---|
| `atelier.core.capabilities.autopilot.workflow_config` | repo `0.2.0` [CITED: `pyproject.toml:1-4`] | Typed workflow state and transitions | Already canonical for `current_step`, `session_phase`, sticky window, and persisted workflow metadata. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:56-174`] |
| Workspace `session_state.json` | repo `0.2.0` | Live mutable per-workspace session state | Already shared by hooks, autopilot, MCP routing, and outcome capture. [CITED: `src/atelier/core/capabilities/autopilot/factory.py:191-222`] [CITED: `src/atelier/gateway/adapters/mcp_server.py:596-635`] |
| `atelier.infra.runtime.run_ledger.RunLedger` | repo `0.2.0` | Durable session events, plan state, blockers, tests, files | Existing trace/reporting backbone; planner should extend this, not replace it. [CITED: `src/atelier/infra/runtime/run_ledger.py:22-99`] [CITED: `src/atelier/infra/runtime/run_ledger.py:392-439`] |

### Supporting

| Library / Module | Version | Purpose | When to Use |
|---|---|---|---|
| `atelier.core.capabilities.plugin_runtime` | repo `0.2.0` | Session stats, event counts, progress/statusline nudges | Use for progress counters and hook-visible workflow summaries. [CITED: `src/atelier/core/capabilities/plugin_runtime.py:1094-1577`] |
| `atelier.infra.runtime.checkpoint` | repo `0.2.0` | Explicit resume checkpoints | Use for resumable boundaries, but not as the sole store for task outputs. [CITED: `src/atelier/infra/runtime/checkpoint.py:37-170`] |
| `atelier.infra.runtime.context_compressor` | repo `0.2.0` | Compact carry-forward / handover summaries | Use for resume/handover text, not structured task output storage. [CITED: `src/atelier/infra/runtime/context_compressor.py:76-181`] |
| Claude hooks (`pre_tool_use`, `session_start`, `post_tool_use`, `user_prompt`) | repo `0.2.0` | Host enforcement, session bridging, edit diff capture, nudges | Use for benchmark-path native host enforcement without touching normal MCP flows. [CITED: `integrations/claude/plugin/hooks/pre_tool_use.py:62-90`] [CITED: `integrations/claude/plugin/hooks/session_start.py:179-224`] [CITED: `integrations/claude/plugin/hooks/post_tool_use.py:191-227`] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|---|---|---|
| Existing `WorkflowState` + workspace state | New workflow engine / DB | Violates locked direction and duplicates already-consumed state. [CITED: `.planning/phases/02-execution-kernel-mvp/02-CONTEXT.md:34-38`] |
| Existing trace/report/session_stats/dashboard | New workflow event bus | Adds a parallel reporting system with overlapping consumers. [CITED: `src/atelier/gateway/adapters/mcp_server.py:1644-1962`] [CITED: `src/atelier/core/capabilities/plugin_runtime.py:1211-1577`] |
| Benchmark-only gating | Global hard edit block | Conflicts with Phase 1’s advisory/fail-open boundary and bloats normal flows. [CITED: `.planning/STATE.md:67-71`] [CITED: `.planning/phases/01-grounded-terminal-loop-mvp/01-03-SUMMARY.md:61-78`] |

**Installation:** No new packages recommended for Phase 2. [CITED: `pyproject.toml:14-46`]

**Package Legitimacy Audit:** Not required; this research does not recommend adding external packages. [CITED: `pyproject.toml:14-46`]

## Architecture Patterns

### Recommended Project Structure

```text
src/atelier/core/capabilities/autopilot/
├── workflow_config.py      # extend canonical WorkflowState first
├── factory.py              # persist live workflow/task state to session_state.json
└── ...                     # small helper module only if task-output logic grows

src/atelier/gateway/adapters/mcp_server.py
# thin wiring: read/update state, emit ledger events, enforce benchmark-only edit gate

integrations/claude/plugin/hooks/pre_tool_use.py
# native-host benchmark-only edit interception
```

### Pattern 1: Extend the existing typed workflow object
**Use:** `WorkflowState` as the canonical session workflow record, then add only Phase-2 fields needed for plan review/current task tracking. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:56-174`]  
**Why:** It is already persisted and already read by routing logic. [CITED: `src/atelier/core/capabilities/autopilot/factory.py:191-222`] [CITED: `src/atelier/gateway/adapters/mcp_server.py:5646-5678`]

### Pattern 2: Live mutable state in workspace JSON, durable audit in ledger
**Use:** Keep “what is current right now?” in `session_state.json`, and mirror user-visible milestones/events into `RunLedger`. [CITED: `src/atelier/core/capabilities/autopilot/factory.py:191-222`] [CITED: `src/atelier/infra/runtime/run_ledger.py:392-439`]  
**Why:** Hooks, MCP, and routing already share the workspace file; reports already read the ledger. [CITED: `src/atelier/gateway/adapters/mcp_server.py:596-635`] [CITED: `src/atelier/infra/runtime/session_report.py:162-203`]

### Pattern 3: Benchmark-only edit gate at the narrowest seams
**Use:** Gate MCP `edit` and host-native Edit/Write/MultiEdit only when benchmark mode/path is active. [CITED: `src/atelier/gateway/adapters/mcp_server.py:5712-5855`] [CITED: `integrations/claude/plugin/hooks/pre_tool_use.py:62-90`] [CITED: `src/atelier/bench/mode.py:24-61`] [ASSUMED]  
**Why:** This satisfies EXEC-05 without regressing the general fail-open Phase 1 loop. [CITED: `.planning/phases/01-grounded-terminal-loop-mvp/01-03-SUMMARY.md:61-78`]

### Anti-Patterns to Avoid
- **Do not create a second workflow state store** beside `session_state.json` + `RunLedger`. [CITED: `src/atelier/core/capabilities/autopilot/factory.py:191-222`] [CITED: `src/atelier/infra/runtime/run_ledger.py:392-439`]
- **Do not rely on checkpoints to preserve task outputs**; current checkpoints store hashes plus compact text, not structured outputs. [CITED: `src/atelier/infra/runtime/checkpoint.py:43-63`] [CITED: `src/atelier/infra/runtime/run_ledger.py:255-289`]
- **Do not treat `_READ_TOOLS` as grounding truth**; it omits ranked `search` and code-intel tools, so it is insufficient for EXEC-05 evidence. [CITED: `src/atelier/gateway/adapters/mcp_server.py:4990-5003`] [CITED: `src/atelier/gateway/adapters/mcp_server.py:4834-4890`] [CITED: `src/atelier/core/capabilities/grounded_loop/search_first.py:23-77`]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Workflow engine | New session/workflow service | `WorkflowState` + workspace `session_state.json` | Already shared across hooks, autopilot, and MCP routing. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:56-174`] [CITED: `src/atelier/gateway/adapters/mcp_server.py:5646-5678`] |
| Progress/event pipeline | New workflow event DB | `RunLedger` + `trace` + `session_stats` + dashboard | Existing consumers already read these artifacts. [CITED: `src/atelier/infra/runtime/run_ledger.py:103-189`] [CITED: `src/atelier/core/capabilities/plugin_runtime.py:1211-1577`] [CITED: `src/atelier/core/service/api.py:3792-4190`] |
| Resume storage | Ad hoc resume blobs | `session_state.json` + `CheckpointStore` + `ContextCompressor` | Existing persistence already separates live state, resumable checkpoints, and handover text. [CITED: `src/atelier/core/capabilities/autopilot/factory.py:191-222`] [CITED: `src/atelier/infra/runtime/checkpoint.py:37-170`] [CITED: `src/atelier/infra/runtime/context_compressor.py:119-181`] |
| Edit diff capture | New diff recorder | existing MCP snapshots / `post_tool_use` diff capture | Both edit paths already know how to capture diffs. [CITED: `src/atelier/gateway/adapters/mcp_server.py:2659-2719`] [CITED: `integrations/claude/plugin/hooks/post_tool_use.py:98-180`] |

**Key insight:** Phase 2 is mostly about **connecting existing state/reporting primitives into one explicit execution kernel**, not inventing new infrastructure. [CITED: `.planning/phases/02-execution-kernel-mvp/02-CONTEXT.md:34-38`]

## Common Pitfalls

### Pitfall 1: Extending autopilot hints without making them canonical state
`WorkflowState` already exists, but today it is mostly used for autopilot/routing hints rather than a full execution kernel. If planners add a second state model elsewhere, routing and hooks will drift. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:56-174`] [CITED: `src/atelier/gateway/adapters/mcp_server.py:5646-5678`]

### Pitfall 2: Assuming checkpoints preserve prior task outputs
They do not. Current checkpoints store hashes and `compact_state`, not the actual structured outputs needed for task resume. [CITED: `src/atelier/infra/runtime/checkpoint.py:43-63`]  
**Avoidance:** persist structured task outputs in workspace state, then optionally summarize/snapshot them into checkpoints. [CITED: `src/atelier/core/capabilities/autopilot/factory.py:191-222`]

### Pitfall 3: Building progress/reporting outside existing consumers
`session_stats`, `session_events`, session reports, and dashboard analytics already exist. A new workflow-only log would strand the data from current statusline/CLI/API surfaces. [CITED: `src/atelier/core/capabilities/plugin_runtime.py:1094-1577`] [CITED: `src/atelier/gateway/cli/commands/sessions.py:152-188`] [CITED: `src/atelier/core/service/api.py:3792-4190`]

### Pitfall 4: Reusing current “read tool” classification for grounding gates
Outcome capture’s `_READ_TOOLS` list is for calibration, not grounding; it misses ranked search and code-intel tools. [CITED: `src/atelier/gateway/adapters/mcp_server.py:4990-5003`]  
**Avoidance:** define an explicit grounding-evidence set for `read/search/context(mode=symbols)/explore/node/callers/callees/usages/impact`. [CITED: `src/atelier/core/capabilities/grounded_loop/search_first.py:47-73`] [ASSUMED]

### Pitfall 5: Making the hard gate global
Phase 1 deliberately kept hooks advisory and fail-open. A universal hard block would widen scope beyond the benchmark path. [CITED: `.planning/phases/01-grounded-terminal-loop-mvp/01-03-SUMMARY.md:61-78`]

## Code Examples

### Existing canonical workflow state
```python
@dataclass(frozen=True)
class WorkflowState:
    current_step: str = "exploration"
    last_step: str = ""
    session_phase: str = "explore"
    sticky_window: int = 0
    advisory_emitted_steps: tuple[str, ...] = ()
```
[CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:56-73`]

### Existing live persistence path
```python
workflow_state, step_cfg, emit_advisory = advance_workflow_state(...)
session_state["workflow"] = workflow_state.to_dict()
```
[CITED: `src/atelier/core/capabilities/autopilot/factory.py:199-208`]

### Existing edit interception seam
```python
if method == "tools/call":
    ...
    result = handler(args)
```
This dispatcher is the narrow MCP seam for benchmark-only edit gating before `tool_smart_edit` runs. [CITED: `src/atelier/gateway/adapters/mcp_server.py:5712-5761`]

## State of the Art

| Old Approach | Current Approach | Impact |
|---|---|---|
| Advisory grounded nudges only | Hard gate only on benchmark path | Keeps normal UX fail-open while satisfying EXEC-05. [CITED: `.planning/phases/01-grounded-terminal-loop-mvp/01-03-SUMMARY.md:61-78`] [ASSUMED] |
| Prompt-inferred workflow only | Persisted typed workflow already exists | Phase 2 should formalize and expose it, not replace it. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:56-174`] |
| Separate reporting ideas | Existing trace/session_report/dashboard/statusline surfaces | Reuse lowers scope and preserves INTL-03. [CITED: `src/atelier/gateway/adapters/mcp_server.py:1644-1962`] [CITED: `src/atelier/core/service/api.py:3792-4190`] |

## Assumptions Log

| # | Claim | Risk if Wrong |
|---|---|---|
| A1 | “Benchmark path” should be keyed off existing benchmark env/modes such as `ATELIER_BENCH_MODE` and the SWE Atelier benchmark modes. [ASSUMED] | Gate may be attached to the wrong execution entrypoint. |
| A2 | Grounding evidence should include ranked search and code-intel tools in addition to plain reads. [ASSUMED] | Gate could undercount legitimate grounding and block valid edits. |

## Open Questions

1. **Which exact execution paths must enforce EXEC-05?**  
   - Known: MCP `edit` and Claude native Edit/Write/MultiEdit have narrow interception points. [CITED: `src/atelier/gateway/adapters/mcp_server.py:5712-5855`] [CITED: `integrations/claude/plugin/hooks/pre_tool_use.py:62-90`]  
   - Unclear: whether non-Claude benchmark hosts must also hard-block native edits in Phase 2. [ASSUMED]  
   - Recommendation: lock the first implementation to benchmark paths already carrying benchmark env/mode markers, then extend host coverage only if the benchmark harness truly uses those paths. [ASSUMED]

2. **How thin should the live plan-review surface be?**  
   - Known: `RunLedger.current_plan` exists, but there is no current MCP tool to set/read plan state. [CITED: `src/atelier/infra/runtime/run_ledger.py:44-74`] [CITED: `src/atelier/gateway/adapters/mcp_server.py:1042-2862`]  
   - Recommendation: add one thin surface over existing state rather than a new plan subsystem. [ASSUMED]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---:|---|---|
| `uv` | required repo command path | ✓ | `0.11.7` [CITED: local shell `uv --version`] | — |
| Python | runtime/tests | ✓ | `3.13.7` [CITED: local shell `python3 --version`] | use `uv run` per project rules |
| `git` | repo/benchmark flows | ✓ | `2.51.0` [CITED: local shell `git --version`] | — |

## Validation Architecture

Skipped because `.planning/config.json` sets `workflow.nyquist_validation` to `false`. [CITED: `.planning/config.json:19-24`]

## Security Domain

Security enforcement is enabled. [CITED: `.planning/config.json:48-51`]

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | no | Existing auth is unrelated to this phase’s core workflow state. [CITED: `src/atelier/core/service/auth.py` summary in project instructions] |
| V3 Session Management | yes | Workspace-scoped `session_state.json`, MCP session bridge, and run/session IDs already exist. [CITED: `src/atelier/gateway/adapters/mcp_server.py:596-723`] [CITED: `integrations/claude/plugin/hooks/session_start.py:191-212`] |
| V4 Access Control | yes | Benchmark-only edit gating is an action-level restriction; keep it explicit and scoped. [ASSUMED] |
| V5 Input Validation | yes | MCP tool schemas + typed workflow normalization should validate all new workflow/task payloads. [CITED: `src/atelier/gateway/adapters/mcp_server.py:93-145`] [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:86-146`] |
| V6 Cryptography | no | Existing hashing in checkpoints is sufficient; no custom crypto should be added. [CITED: `src/atelier/infra/runtime/checkpoint.py:29-90`] |

**Known threat patterns**
- Session-state tampering or stale writes → validate and normalize all loaded workflow/task state before use. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:91-111`]
- Ungrounded benchmark edits → require recent grounding evidence at the actual edit seam, not prompt heuristics alone. [CITED: `integrations/claude/plugin/hooks/user_prompt.py:208-247`] [CITED: `src/atelier/gateway/adapters/mcp_server.py:5712-5855`] [ASSUMED]
- Resume with stale or partial task output → make structured task outputs explicit in live state; do not trust checkpoint hashes as data. [CITED: `src/atelier/infra/runtime/checkpoint.py:43-63`]

## Sources

### Primary
- `src/atelier/core/capabilities/autopilot/workflow_config.py` - existing typed workflow model and transitions
- `src/atelier/core/capabilities/autopilot/factory.py` - persistence of workflow into workspace state
- `src/atelier/gateway/adapters/mcp_server.py` - workspace state helpers, trace tool, tool dispatch seam, routing consumption of workflow
- `src/atelier/infra/runtime/run_ledger.py` - current plan/event persistence primitives
- `src/atelier/infra/runtime/checkpoint.py` - resumable checkpoint capabilities and limitations
- `src/atelier/infra/runtime/context_compressor.py` - compact/handover carry-forward patterns
- `src/atelier/core/capabilities/plugin_runtime.py` - existing progress/session stats/statusline pipeline
- `src/atelier/core/service/api.py` - existing dashboard/report surfaces
- `integrations/claude/plugin/hooks/pre_tool_use.py` / `session_start.py` / `post_tool_use.py` / `user_prompt.py` - host enforcement and session bridge
- `src/atelier/bench/mode.py` - existing benchmark mode env flag
- `src/benchmarks/swe/modes.py` / `agent_runner.py` / `task_runner.py` - benchmark workflow event plumbing

### Secondary
- `.planning/phases/02-execution-kernel-mvp/02-CONTEXT.md`
- `.planning/STATE.md`
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- Phase 1 summaries under `.planning/phases/01-grounded-terminal-loop-mvp/`

## Metadata

**Confidence breakdown**
- Standard stack: **HIGH** — almost entirely derived from current code paths.  
- Architecture: **HIGH** — seams are explicit in existing modules/tests.  
- Pitfalls: **MEDIUM** — benchmark-path scope and exact host coverage still need confirmation.

**Most important planning takeaways**
- Extend the existing `WorkflowState`; do not invent a new engine. [CITED: `src/atelier/core/capabilities/autopilot/workflow_config.py:56-174`]
- Store live task outputs in workspace state, not checkpoints alone. [CITED: `src/atelier/infra/runtime/checkpoint.py:43-63`]
- Reuse `RunLedger` + `trace` + `session_stats` + session report/dashboard for plan/progress/workflow visibility. [CITED: `src/atelier/infra/runtime/run_ledger.py:392-439`] [CITED: `src/atelier/core/capabilities/plugin_runtime.py:1211-1577`] [CITED: `src/atelier/core/service/api.py:3792-4190`]
- Put the hard edit gate at the benchmark edit seam only, using explicit grounding evidence. [CITED: `src/atelier/gateway/adapters/mcp_server.py:5712-5855`] [CITED: `integrations/claude/plugin/hooks/pre_tool_use.py:62-90`] [ASSUMED]
