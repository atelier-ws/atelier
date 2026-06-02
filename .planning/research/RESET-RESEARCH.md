# Atelier Reset Research Dump

## Purpose

This document preserves the research that informed the brownfield reset of Atelier so later planning phases do not need to rediscover the same findings from scratch.

## Sources Covered

### Current Atelier Repo

- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/CONCERNS.md`
- `.planning/codebase/INTEGRATIONS.md`
- `.planning/codebase/STACK.md`
- `docs/reference.md`

### Eval

- `/home/pankaj/Projects/eval/README.md`
- `/home/pankaj/Projects/eval/internal/config/defaults/settings.json`
- `/home/pankaj/Projects/eval/internal/daemon/vfs.go`
- `/home/pankaj/Projects/eval/internal/daemon/workflow.go`
- `/home/pankaj/Projects/eval/internal/daemon/session.go`
- `/home/pankaj/Projects/eval/internal/daemon/session_read_gate.go`
- `/home/pankaj/Projects/eval/internal/daemon/sandbox.go`
- `/home/pankaj/Projects/eval/internal/daemon/sandbox_landlock.go`
- `/home/pankaj/Projects/eval/internal/daemon/llm/stream.go`
- `/home/pankaj/Projects/eval/internal/daemon/session_todo.go`
- `/home/pankaj/Projects/eval/internal/protocol/plan.go`
- `/home/pankaj/Projects/eval/internal/ui/model.go`

### WOZ Source Repo

- `/home/pankaj/Projects/baseline-plugin/README.md`
- `/home/pankaj/Projects/baseline-plugin/settings.json`
- `/home/pankaj/Projects/baseline-plugin/agents/code.md`
- `/home/pankaj/Projects/baseline-plugin/agents/explore.md`
- `/home/pankaj/Projects/baseline-plugin/hooks/hooks.json`
- `/home/pankaj/Projects/baseline-plugin/.mcp.json`
- `/home/pankaj/Projects/baseline-plugin/unobf/servers/code-server/deobfuscated.js`
- `/home/pankaj/Projects/baseline-plugin/unobf/scripts/tool-redirect-hook/deobfuscated.js`
- `/home/pankaj/Projects/baseline-plugin/unobf/scripts/session-telemetry-hook/deobfuscated.js`
- `/home/pankaj/Projects/baseline-plugin/unobf/scripts/edit-batching-nudge/deobfuscated.js`

### Installed WOZ Plugin / Runtime

- `/home/pankaj/.claude/settings.json`
- `/home/pankaj/.claude/baseline/`
- `/home/pankaj/.claude/plugins/cache/baseline-marketplace/feature/0.3.75/.mcp.json`
- `/home/pankaj/.claude/plugins/cache/baseline-marketplace/feature/0.3.75/agents/code.md`
- `/home/pankaj/.claude/plugins/cache/baseline-marketplace/feature/0.3.75/agents/explore.md`
- `/home/pankaj/.claude/plugins/cache/baseline-marketplace/feature/0.3.75/hooks/hooks.json`
- `/home/pankaj/.claude/plugins/cache/baseline-marketplace/feature/0.3.75/scripts/router-config.jsonc`
- `/home/pankaj/.local/bin/baseline`
- `/home/pankaj/.local/bin/claude-feature`
- `/home/pankaj/.feature/`

### Prior Claude Session State

- `/home/pankaj/.claude/baseline/sessions/dc487308-380f-41b9-9c2d-a11f555b158c.json`
- `/home/pankaj/.claude/projects/-home-pankaj-Projects-leanchain-atelier/dc487308-380f-41b9-9c2d-a11f555b158c.jsonl`

## User Goal Locked During Research

- Brownfield retrofit, not a clean-slate rewrite.
- Terminal-first core.
- Reach Eval-level planning/execution quality with materially lower token spend on benchmarked terminal tasks.
- Preserve all three WOZ-inspired qualities:
  - strong recall/context memory
  - sharper code-intel UX / path-first concise answers
  - workflow ergonomics / host-side behavior shaping
- Only remove current Atelier surfaces after a measured parity review.

## What Atelier Already Has And Must Not Regress

- Strong context + memory composition across runtime, archival recall, and host-facing flows.
- Dedicated code-intel surfaces: symbols, node, callers, callees, usages, impact, pattern, and explore.
- Host-side enforcement and telemetry through plugin hooks.
- Durable run ledger / trace infrastructure.
- Existing routing foundations that are stronger than either Eval or WOZ on paper, even though execution enforcement is still weak.

## Codebase Shape Problems Driving The Reset

- The repo is broad: CLI, MCP, HTTP API, SDK, frontend, host integrations, benchmarking, tracing, and memory systems.
- Several central modules are very large and multi-responsibility, especially:
  - `src/atelier/core/capabilities/code_context/engine.py`
  - `src/atelier/core/service/api.py`
  - `src/atelier/gateway/adapters/mcp_server.py`
- Default high-frequency terminal paths are fragmented across many tools and surfaces.
- The current product shape feels more like a platform with many surfaces than a focused terminal-first core.

## What Eval Contributes

### Strongest Code-Backed Mechanisms

- A real workflow/session kernel with explicit step execution, branching, state, and reuse.
- Workflow-local prompt churn reduction via step outputs, variables, and state carry-forward.
- Minified virtual filesystem read/edit/write path for token savings.
- Read-before-edit gate.
- Sandboxed bash execution.
- Thinking stall detection and retry behavior.
- Typed plan/proposal/action objects with an approval loop.
- Session-owned TODO/task state.

### What Not To Copy

- Do not copy the full workflow DSL or bash-templated control flow.
- Do not copy Eval wholesale as a product shape.
- Do not copy broad prompt stuffing just because it exists.

### Main Takeaway

Eval's biggest real advantage is not marketing-level "project brain." It is the presence of a real workflow kernel and compression/cache mechanics that reduce prompt churn and guide execution.

### Expanded Eval Detail

#### Workflow / Session Architecture

- `Session` is the actual runtime owner. It carries conversation state, turn snapshots for fork/trim, active workflow state, background task registry, bash jobs, loaded agents/workflows, read-set, TODO state, and workflow message buffering in one object.
- The main session loop handles typed commands such as session input, workflow execution, model switching, trim, and close rather than relying on loose prompt conventions.
- `WorkflowDef` / `WorkflowStepDef` form a real workflow graph with step kinds (`agent`, `tool`, `bash`), branching, `fork_from`, `deny_tools`, JSON output handling, and per-step timeouts.
- Workflow execution is evented: start, step start, step done, and complete events are emitted with token and cost context.
- Persistent step agents matter: Eval keeps prior messages and can clone agent state for `fork_from` reuse, which is the real mechanism behind explore -> plan -> refine reuse.
- Plan review is not implicit. Typed plan/proposal/action objects and explicit user review flows exist in the protocol/UI loop.
- Background tasks are real runtime objects, not just prompts about subagents.

Relevant files:

- `/home/pankaj/Projects/eval/internal/daemon/session.go`
- `/home/pankaj/Projects/eval/internal/daemon/workflow.go`
- `/home/pankaj/Projects/eval/internal/protocol/types.go`
- `/home/pankaj/Projects/eval/internal/protocol/plan.go`
- `/home/pankaj/Projects/eval/internal/ui/model.go`
- `/home/pankaj/Projects/eval/internal/config/defaults/settings.json`

#### Prompt / Token Saving Mechanisms

- Workflow-local history reuse is one of the biggest real savings levers. `fork_from` lets later steps inherit earlier step state instead of rebuilding context from scratch.
- Step-local outputs become variables for later steps, which reduces repeated prompting and keeps flow state inside the workflow itself.
- JSON output / display extraction lets Eval keep structured outputs while showing only a compact summary in the UI.
- The minified VFS is a real implementation, not just a claim: reads can be minified after line slicing, and edits/writes are translated back into formatted source.
- Read-before-edit is enforced, which keeps edit flows grounded in explicit file reads.
- Output caps and continuation behavior exist for subagents and workflows, which helps bound runaway generation.

Relevant files:

- `/home/pankaj/Projects/eval/internal/daemon/workflow.go`
- `/home/pankaj/Projects/eval/internal/daemon/vfs.go`
- `/home/pankaj/Projects/eval/internal/daemon/session_read_gate.go`
- `/home/pankaj/Projects/eval/internal/daemon/subagent.go`
- `/home/pankaj/Projects/eval/internal/config/defaults/settings.json`

#### Safety / Execution Controls

- Bash execution uses real sandbox selection logic rather than only prompt rules: Landlock on Linux when available, bubblewrap fallback, Seatbelt on macOS, else unsandboxed fallback.
- Directory and write approvals are wired in code and happen before risky execution.
- Tool calls have bounded timeouts, and workflow bash steps can branch on timeout instead of only failing hard.
- Session, workflow, and subagent loops all have extended-thinking stall detection with retries and a final no-thinking fallback.
- TODO management is structured and validated, with dependency checks and updates emitted as events.

Relevant files:

- `/home/pankaj/Projects/eval/internal/daemon/sandbox.go`
- `/home/pankaj/Projects/eval/internal/daemon/sandbox_landlock.go`
- `/home/pankaj/Projects/eval/internal/daemon/session.go`
- `/home/pankaj/Projects/eval/internal/daemon/workflow.go`
- `/home/pankaj/Projects/eval/internal/daemon/llm/stream.go`
- `/home/pankaj/Projects/eval/internal/daemon/session_todo.go`

#### README / Marketing Claims That Are Weaker In Code

- "Project brain" is still much more roadmap/positioning than a clearly demonstrated reusable system in the inspected code.
- "Stem agents" maps to persistent `AgentRunner` history and `fork_from` cloning, not to a broad standalone abstraction.
- Claims around broad voting / MAKER-like control are only partially backed by the code that was inspected.
- The strongest code-backed parts are still workflow reuse, minified VFS, read gates, sandboxing, and stall handling.

Relevant files:

- `/home/pankaj/Projects/eval/README.md`
- `/home/pankaj/Projects/eval/internal/daemon/session.go`
- `/home/pankaj/Projects/eval/internal/daemon/workflow.go`

#### What Atelier Should Borrow First vs Later

Borrow first:

- A session-owned workflow object with explicit step state and workflow events.
- Persistent step-local history reuse similar to `fork_from`.
- Step result variables / structured outputs to avoid re-prompting.
- Read-before-edit gating.
- Minified read/edit path where safe.
- Timeout caps, stall detection, and explicit TODO/task state.

Defer:

- The full workflow DSL surface.
- Broad "project brain" claims before there is measured support.
- Extra Eval product surfaces that are not part of the terminal-first milestone.

## What WOZ Source Contributes

### Strongest Code-Backed Mechanisms

- A very small default mental model: Search / Edit / Sql / Recall.
- Combined Search behavior that collapses discovery, grep, and read into a single decisive surface.
- Edit batching nudges and a bias toward multi-edit operations.
- Recall as a first-class MCP surface.
- SQL as a first-class MCP surface.
- Hook-driven soft routing away from wasteful native shell patterns.
- A cheap read-only explore path.
- Strong savings/status UX.

### What Not To Copy

- Do not replace Atelier's stronger code-intel with generic search.
- Do not inherit WOZ's exact prompting and account assumptions.
- Do not mistake WOZ's source repo for a complete provider-routing architecture.

### Main Takeaway

WOZ's biggest real advantage in source form is host/tool ergonomics and default-path discipline, not vendor-routing depth.

## What The Installed WOZ Plugin Changed

The installed plugin changed one important conclusion: WOZ does ship a real local router subsystem, even though it was not active on this machine during the prior session.

### Installed Router Findings

- `baseline` dispatches to a router daemon implementation and router config bundle.
- `router start` rewrites Claude host env toward a local endpoint similar to:
  - `ANTHROPIC_BASE_URL=http://127.0.0.1:8880/router-preset/claudecode`
- `router apply` refreshes Claude model-picker cache.
- `router serve` runs a local HTTP service on port `8880`.
- Installed router config includes providers, bindings, and routing presets.
- In this environment the router is dormant:
  - daemon not running
  - no router config present under `~/.feature/`
  - current live behavior remains MCP redirection, recall, and telemetry

### Updated Takeaway

WOZ is more relevant to Atelier's routing design than the source-only pass suggested, but it is still primarily a host/plugin orchestration pattern rather than a reusable routing architecture for Atelier as a product.

## Prior Session Evidence Worth Keeping

The earlier WOZ-driven Claude session produced concrete savings telemetry that is useful as product inspiration, even though it is not proof of benchmark superiority by itself.

- `totalWozCalls=129`
- `equivalentClaudeCalls=383`
- `callsSaved=254`
- `tokensSaved=25385416`
- `costSavedInUsd=13.21`

Other important prior-session findings:

- The session was WOZ-first and tool-redirect heavy.
- It showed repeated `403` issues when trying `anthropic.claude-opus-4-8` in that older environment.
- In the current Copilot CLI environment, deep delegated research was still possible, but the prior session proved model access may vary by host/provider path.

## Four Focused Research Threads Completed In This Session

### 1. Terminal Tool UX Gap

Converged answer:

- Milestone 1 should make a Search-first default terminal path.
- That path should preserve Atelier's stronger code-intel as the escalation path, not replace it.
- Edit/Recall/Sql ergonomics and host-side nudges matter more than adding brand new engines.

### 2. Workflow Loop Gap

Converged answer:

- Atelier needs a typed workflow kernel, not just better prompts.
- Milestone 1 should introduce explicit plan review, task-local carry-forward state, and a single session workflow object.
- Reuse Atelier's existing autopilot/routing/ledger foundations instead of rebuilding from zero.

### 3. Routing Gap

Converged answer:

- Atelier already has strong advisory routing and ranking logic.
- The real missing piece is provider execution enforcement.
- Milestone 1 should enforce routing only where Atelier owns execution, not on the top-level host conversation.

### 4. Benchmark And Savings Gap

Converged answer:

- Atelier already has benchmark and telemetry infrastructure.
- The missing piece is a single canonical milestone-1 benchmark definition.
- Success needs paired repeated runs, frozen task sets, raw artifacts, non-inferior quality, and materially lower cost/token spend.

## Final Converged Milestone-1 Shape

Milestone 1 should be built around four connected moves:

1. A combined Search-first default tool path with WOZ-style ergonomics.
2. A typed workflow kernel with explicit plan review and task-local carry-forward state.
3. Enforced provider routing only on Atelier-owned subcalls.
4. A paired benchmark gate that proves lower spend without sacrificing terminal-task quality.

## Anti-Goals Locked By Research

- No clean-slate rewrite.
- No speculative removal of existing Atelier surfaces before parity review.
- No web-first repositioning.
- No full top-level host override in milestone 1.
- No copying Eval or WOZ wholesale.
- No cost claims based only on UX counters without benchmark quality evidence.

## Why This Research Must Be Retained

Without this record, later phases are likely to rediscover:

- that Eval's value is mostly workflow kernel + compression mechanics
- that WOZ's value is mostly host/tool ergonomics plus an optional local router daemon
- that Atelier already has stronger memory and code-intel foundations than either
- that the reset should focus on a narrow milestone-1 shape instead of another broad platform expansion

This file exists to prevent that reset drift.
