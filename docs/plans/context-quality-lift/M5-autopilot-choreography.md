# M5 — Autopilot choreography (hook-driven auto-fire of context capabilities)

> Parent: [`index.md`](index.md). Grounding: [`grounding.md`](grounding.md).

## Goal

Give a **turnkey, "it just does the right thing" experience** to users who have
not wired up an external orchestrator. Atelier's context capabilities
(M1 lineage, M4 scoped pull, recall, lessons, failure analysis) already exist —
but today the agent has to *explicitly call* the MCP tools to benefit. M5 adds a
thin **choreography layer** that fires those capabilities automatically at host
lifecycle events, so the right context shows up without anyone invoking a tool.

The layer is **opt-in**, **fail-open**, and **transparent under any
orchestrator**: the same auto-fire that helps a solo user also runs underneath
every subagent an external multi-agent harness (e.g. GSD) spawns.

## Choreography is not orchestration (the load-bearing boundary)

This milestone deliberately draws a hard line:

| | Choreography (this plan) | Orchestration (out of scope) |
|---|---|---|
| Who drives the model | The host / external harness | — |
| What Atelier does | Sequences **its own** capabilities in response to host events | Decides phases, spawns subagents, drives the LLM |
| Conversation ownership | Host owns it | — |

Atelier never opens a model conversation, never manages phases, never spawns
agents. It only reacts to events the host already emits and injects/records
context. If a behavior needs Atelier to "call the model and decide what to do
next," it belongs to an orchestrator, not here. (See the removed phase-linear
runner for the anti-pattern this boundary exists to prevent.)

## Background

The Claude plugin already ships the exact hook surface required, but the hooks
are **passive recorders** today:

- `integrations/claude/plugin/hooks/user_prompt.py` — logs the prompt to the
  RunLedger; injects nothing.
- `integrations/claude/plugin/hooks/session_start.py` — captures session
  metadata; warms nothing.
- `pre_tool_use.py` / `post_tool_use*.py` — track tool-level savings; feed
  nothing back.
- `stop.py` — session stats + auto-record.

The host supports hook-driven context injection (e.g. `UserPromptSubmit` and
`PostToolUse` may return `hookSpecificOutput.additionalContext`). M5 turns the
passive hooks proactive by routing them through a single core policy.

## Module layout

Per the repo invariant (`CLAUDE.md`): the brain lives in `core/capabilities/`;
hooks stay thin dispatchers.

```
src/atelier/core/capabilities/autopilot/   (new)
  __init__.py
  capability.py     — AutopilotCapability: on_event(event) -> AutopilotAction
  policy.py         — which behaviors fire for which event + budget/dedup guards
  models.py         — AutopilotEvent, AutopilotAction (inject | record | noop)
integrations/claude/plugin/hooks/          (extend, thin)
  session_start.py  — call AutopilotCapability.on_event("session_start")
  user_prompt.py    — call on_event("user_prompt"); emit additionalContext
  post_tool_use.py  — call on_event("post_edit"); emit counterexample context
```

Reuses without modification:

- `core/capabilities/archival_recall/` — session-start memory warm.
- `core/capabilities/lesson_promotion/` — surface repo/branch lessons.
- `core/capabilities/scoped_context/` (**M4**) — per-prompt scoped pull.
- `core/capabilities/failure_analysis/` — structure post-edit check output.
- `core/capabilities/prefix_cache/planner.py` — choose a cache-stable injection
  position (**M2**).
- `core/capabilities/context_compression/minify.py` — already on the read path;
  injected bodies go through it too.

## Behaviors (each maps to one existing hook)

| Host event | Auto-fired behavior | Powered by | Ships in |
|---|---|---|---|
| `SessionStart` | Warm repo/branch memory + relevant lessons into a short note | `archival_recall`, `lesson_promotion` | Phase 1 (cheap, no cache risk) |
| `UserPromptSubmit` | Pull **scoped** context for the prompt; inject as `additionalContext` | `scoped_context` (M4) + M1 chunks | Phase 2 (requires M4) |
| `PostToolUse` (edit/write) | Run deterministic checks; feed failures back as a **counterexample**, not pass/fail | `failure_analysis` (+ M3 loop) | Phase 3 (requires M3) |
| `PreToolUse` (read/edit) | Attach the target file's lineage + recent failures | M1 + `failure_analysis` | Phase 3 |

Phasing is deliberate: only Phase 1 is safe to ship before M4. The prompt-
injection behaviors are **gated on M4 scoping** (see Safety).

## Control surface (opt-in, opt-out)

- Master switch: env `ATELIER_AUTOPILOT` (default **off** for now) and plugin
  setting `autopilot` in `PLUGIN_DEFAULT_SETTINGS`.
- Per-behavior toggles in the plugin settings block so a user can keep
  session-start warm but disable prompt injection.
- All hooks remain **fail-open**: any error in the autopilot path exits 0 and
  injects nothing — never blocks the agent (matches current hook contract).

## Safety rules (why naive auto-context hurts, and how we avoid it)

1. **Scope before inject.** Per-prompt injection MUST go through M4
   `scoped_context.pull(...)`, never broad retrieval. Unscoped auto-injection is
   context spam — it raises cost and pollutes the window. Phase 2 does not ship
   until M4's precision target is met.
2. **Cache-stable position.** Injected context is placed at a position the
   `prefix_cache/planner` reports as non-invalidating, so auto-injection does
   not thrash the host's KV-cache (ties to M2). If no stable position exists,
   skip injection rather than evict the prefix.
3. **Budget + dedup.** `policy.py` caps injected tokens per event and suppresses
   re-injecting context already present earlier in the session.
4. **No model calls in the hot path.** Any LLM work (e.g. M1 commit summaries)
   runs in the background; the hook reads precomputed artifacts only.
5. **Deterministic & idempotent.** Same event + same repo state ⇒ same action.

## Interaction with external orchestrators

Because the layer is hook-driven, it fires underneath **every** subagent the
host spawns — including those created by an external multi-agent harness. Net
effect: the same choreography that gives a solo user the turnkey feel also
silently improves orchestrated runs. Autopilot and an external orchestrator are
complementary; Autopilot never competes for control of the loop.

## Telemetry

Each fired behavior emits a record to the run-ledger session file:

```json
{
  "event": "autopilot_action",
  "trigger": "user_prompt",
  "behavior": "scoped_inject",
  "injected_tokens": 1840,
  "deduped": false,
  "cache_safe_position": true,
  "decision": "injected"
}
```

Feeds the savings/quality dashboard so the value (and any over-injection) is
measurable, not assumed.

## Validation

Tests under `tests/core/test_autopilot/`:

- `test_disabled_by_default.py` — with `ATELIER_AUTOPILOT` unset, `on_event`
  returns a `noop` action and hooks inject nothing.
- `test_session_start_warms_recall.py` — Phase 1: action carries repo/branch
  recall + lessons within the token cap.
- `test_prompt_inject_uses_scoped_pull.py` — Phase 2: injection path calls
  `scoped_context.pull` (never broad retrieval).
- `test_inject_skipped_when_cache_unstable.py` — when planner reports no stable
  position, action is `noop`.
- `test_dedup_suppresses_repeat.py` — context already in-session is not
  re-injected.
- `test_fail_open.py` — an exception in the policy yields exit 0 / `noop`.

Benchmark under `tests/benchmarks/context_quality/M5_autopilot.py`:

- 20 multi-file edits from this repo's history, run twice: Autopilot off vs. on.
- Metric A (quality): % of tasks whose patch passes the original PR tests.
- Metric B (cost): total tokens injected vs. quality delta — guardrail against
  context spam.
- Target: quality at least equal to M4-enabled baseline at **≤10% added
  injected tokens**; no regression when Autopilot is off.

## Exit criteria

- `autopilot` capability lands with the policy + behaviors above; hooks call it
  and stay thin.
- Off by default; master + per-behavior toggles work; all hooks fail-open.
- Phase 1 (session-start warm) shipped and benchmarked.
- Phases 2–3 gated on M4 / M3 respectively and documented as such.
- Telemetry rows present in the ledger.
- No regression in existing hook tests or `tests/core/test_code_context.py`.

## Dependencies

- **Phase 1** (session-start warm): no milestone dependency — ships first.
- **Phase 2** (scoped prompt injection): requires **M4** (and benefits from
  **M1**, **M2**).
- **Phase 3** (counterexample / lineage on tool use): requires **M3** (and
  **M1**).

## Open questions

- Default state: ship **off** (current plan) and let users opt in, or ship
  Phase-1-on once it is proven harmless? Lean toward off until the M5 benchmark
  confirms no regression.
- Injection channel for `UserPromptSubmit`: `additionalContext` vs. a synthetic
  tool result. `additionalContext` is simpler but host-specific; document the
  fallback for hosts that lack it (degrade to `noop`).
- Should Phase 1's warm note be regenerated per session or cached per
  repo/branch with a TTL? Lean toward cached-with-TTL to keep session start fast.
