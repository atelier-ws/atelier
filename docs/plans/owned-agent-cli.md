# Design — `atelier` as a user-owned coding-agent CLI (max cache control)

> **Status:** 📝 Proposed — **design only**. Research and implementation are left to
> the implementing agent. This document fixes the architecture, surfaces, and
> contracts; it does not write production code.
>
> **Owner (suggested):** `core/capabilities/owned_execution_*` +
> `gateway/cli` + `core/capabilities/cross_vendor_routing` +
> `core/capabilities/context_compression` + `core/capabilities/context_dedup`.

## Why this exists (the unlock)

Today Atelier is a **guest** inside a host CLI (Claude Code, Codex, …). The host
owns the model API call, so Atelier cannot set `cache_control` breakpoints, cannot
force cache reads, and cannot keep a byte-stable prefix across phases. Its only
levers on the host bill are indirect (smaller/stable tool output, dedup,
compaction timing — all shipped in Part 1).

The biggest savings lever — **phase-linear warm-prefix reuse** — was explicitly
shelved for this reason. See `docs/plans/phase-linear-cache-reuse[infeasible]`:

> "[Infeasible] for now unless Atelier becomes a CLI itself."

**This plan is that CLI.** When Atelier makes the model call on the user's own
credentials, it gains full control of the prompt cache and the phase-linear plan
becomes feasible. The owned-execution runtime already exists
(`owned_execution_routing.py`, `owned_execution_lanes.py`, cache-affinity,
`cache_policy: inherit`); this plan turns that engine into a first-class,
user-drivable coding agent rather than an internal sub-agent spawner.

## Problem

Users want a coding agent/CLI that:

1. runs on **their own API credentials** (no Atelier-hosted key, no host-CLI
   subscription dependency), and
2. gives **maximum cache control** so a multi-step coding task re-reads its
   ingested context as cache hits (~0.1×) instead of fresh input (1×) or repeated
   cache writes (~1.25×).

The existing owned-execution path is API-only (litellm/openai transports) and is
driven internally (the hidden `workflow` tool, the `agent` MCP tool). There is no
user-facing CLI to start, drive, and observe an owned coding session, and no
explicit cache-control layer (breakpoints, phase-linear prefix, minified reads).

## Goals

- A `atelier` CLI surface to run an owned coding agent end-to-end on user creds.
- Maximum, explicit cache control: stable system prefix, phase-linear single
  conversation, `cache_control` breakpoints, cache affinity, minified reads.
- Reuse — not reinvent — the existing owned-execution, routing, compression,
  dedup, and savings machinery.
- Honest per-run cache economics reporting (read/write/fresh split, $ vs naive).

## Non-goals

- No new/better model; quality tracks the underlying model exactly.
- Not a host-CLI replacement for users happy inside Claude Code/Codex.
- No Atelier-hosted inference or key brokering — strictly the user's own creds.
- Not a redesign of the host-guest path (Part 1 already covered that).

## Scope

### A. CLI surface (design the command tree; names are proposals)

- `atelier code "<task>"` — run an owned coding session in the cwd repo.
  - `--provider/--model` (explicit) or `--budget cheap|balanced|best` (auto-route
    via existing `select_owned_route`).
  - `--cache-policy inherit|fresh` (default `inherit`).
  - `--phase-linear/--no-phase-linear` (default on) — Survey→Plan→Implement in one
    byte-stable conversation.
  - `--max-cost`, `--yolo/--approve-edits`, `--dry-run`.
- `atelier code resume <session-id>` — continue with the warm prefix intact.
- `atelier code report <session-id>` — per-run cache economics + cost-vs-naive.
- Credential discovery reuses `detect_api_key_vendors` (env / `.env`); the CLI
  refuses to start (clear message) when no key is configured rather than routing
  to an unexecutable transport.

### B. Cache-control layer (the heart of "maximum control")

1. **Fixed system prefix.** One system prompt for the whole run; never edited
   mid-run. All per-phase intent goes in injected **user** turns so the prefix
   stays byte-stable and cacheable. (Directly implements the phase-linear plan.)
2. **Explicit `cache_control` breakpoints.** Place an ephemeral breakpoint after
   the stable prefix (system + tools + pinned context) so the ingested codebase
   is written once and re-read as a hit. Reuse the `stable_prefix` /
   `dynamic_tail` split already in `owned_execution_lanes.py`.
3. **Phase-linear single conversation.** Survey (read) → Plan → Implement run as
   one conversation; Plan reads Survey's history as a cache hit. Fall back to a
   fresh sub-context only when a step genuinely needs divergence, or when the
   conversation has grown so large the cached prefix itself is the cost (then
   compact — reuse `context_compression`).
4. **Whitespace-minified reads** on the read path (Survey/Plan); exact bytes on
   the Implement/edit path. (Lever 2 from the phase-linear rationale.)
5. **Cache affinity / inherit by default.** Keep subsequent owned calls on the
   provider/model whose prefix is warm (existing `_sticky_affinity_candidate`,
   `cache_affinity`, `cache_policy: inherit`).
6. **Within-session content dedup.** Reuse Part 1's `context_dedup` so re-reads
   inside the run don't re-enter the prefix.

### C. Reporting

- Per-run receipt: cache-read vs cache-write vs fresh-input tokens, cache
  efficiency %, $ spent, and $ vs a naive (no-cache, per-phase-cold) baseline.
- Reuse the Part 1 savings/cache-split plumbing (`savings_summary`,
  compaction crediting) so numbers are consistent across host and owned paths.

## Architecture (reuse map)

| Concern | Existing component to build on |
|---|---|
| Provider/model selection on user creds | `owned_execution_routing.select_owned_route`, `detect_api_key_vendors`, `load_route_config_or_default` |
| Making the API call (own key) | `owned_execution_lanes.execute_owned_prompt` (litellm/openai transports) |
| Stable-prefix / dynamic-tail + cache metadata | `owned_execution_lanes` (`stable_prefix_hash`, cache_metadata) |
| Cache affinity / warm route | `_sticky_affinity_candidate`, `cache_affinity_for_route`, `cache_policy: inherit` |
| Compaction when prefix grows too large | `core/capabilities/context_compression` |
| Within-run read dedup | `core/capabilities/context_dedup` (Part 1) |
| Cost / cache-split reporting | `core/capabilities/savings_summary` (Part 1 cache-split + compaction credit) |
| Code intel for Survey/Implement | existing code-intel engine + MCP tool fns |
| CLI wiring | `gateway/cli` (keep entry-point logic thin per architecture rules) |

## Credential model

- User's own keys only, discovered from env / `.env` via `detect_api_key_vendors`
  (and any litellm-compatible base-url/token, e.g. `ANTHROPIC_BASE_URL` +
  `ANTHROPIC_AUTH_TOKEN`, for OpenRouter/Bedrock/Vertex-style setups).
- No key ⇒ the CLI exits with an actionable message (which env vars to set);
  it must never silently route to a transport it cannot execute.
- Keys are read at call time and never persisted by Atelier.

## Milestones (for the implementing agent)

1. **M0 — Research.** Confirm exact `cache_control` breakpoint semantics per
   transport (litellm, openai, anthropic-direct), TTL behavior, and how the
   chosen client library surfaces cache-read/write token counts. Validate the
   phase-linear cache-hit assumption with a throwaway 2-phase probe on the
   user's own key.
2. **M1 — Owned session core.** A drivable owned coding session (single shot)
   on user creds: route → execute → receipt, with stable prefix + one cache
   breakpoint. No phases yet.
3. **M2 — Phase-linear conversation.** Survey/Plan/Implement in one byte-stable
   conversation; per-phase user headers; measured cache-hit on Plan.
4. **M3 — Minified reads + dedup + compaction fallback** wired into the read
   path.
5. **M4 — CLI surface** (`atelier code`, `resume`, `report`) + credential
   discovery + approvals/cost guardrails.
6. **M5 — Reporting** parity with Part 1 (cache split, $ vs naive baseline).

## Dependencies

- Part 1 (this PR): `context_dedup`, cache-split reporting, compaction crediting,
  `load_route_config_or_default` / `detect_api_key_vendors`.
- `docs/plans/phase-linear-cache-reuse[infeasible]` — this plan is its enabler;
  fold its rationale (00) and design-spec (02) in once M2 lands and flip it to
  feasible.
- Existing owned-execution + cross-vendor routing + context-compression modules.

## Validation

- A read-heavy 3-phase task shows **Plan-phase input billed as cache reads**
  (cache-read tokens ≈ Survey prefix size), verified from the transport's usage
  numbers — not inferred.
- End-to-end $ for the phase-linear run is materially below a per-phase-cold
  baseline on the same task/model (target: the 30–40% class of savings, measured
  not assumed).
- Runs on the user's own key with no host-CLI subscription present.
- `make lint && make typecheck && make test` green; new logic unit-tested in
  `core/capabilities/`, CLI kept thin.

## Open questions

- **Transport for max cache control:** litellm (broad provider reach) vs
  anthropic-direct (richest cache-control + 1-hour TTL option). Possibly
  per-provider.
- **Cache TTL strategy:** 5-min (1.25× write) vs 1-hour (2× write) — worth it for
  long phase-linear runs? Decide from M0 numbers.
- **Tool-use loop:** does the owned agent expose the full Atelier MCP tool set to
  itself, and how do tool definitions stay inside the cached prefix (adding/
  reordering tools busts the cache)?
- **Edit application & approvals:** reuse `tool_supervision` edit path; what is
  the default safety posture for a headless owned run?
- **Multi-provider affinity:** when routing prefers a cheaper vendor mid-run, is
  the warm-prefix loss ever worth the per-token win? (cost model already has the
  eviction-cost comparison; confirm it covers this.)
