# Design — `atelier` as a user-owned coding-agent CLI (max cache control)

> **Status:** 📋 **Research complete** — design and implementation are left to
> the implementing agent. This document fixes the architecture, surfaces,
> contracts, and research findings; it does not write production code.
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

## Research — existing projects and patterns

Before writing production code, the landscape of CLI coding agents was surveyed
to extract proven patterns and validate the phase-linear cache assumption.

### Vix (github.com/get-vix/vix) — strongest evidence for phase-linear

Vix (AGPL-3.0, Go, 187 stars) is the **closest existing implementation** to this
plan and provides the strongest validation that phase-linear works in production.

| Metric             | Vix vs Claude Code (7-task benchmark) |
| ------------------ | ------------------------------------- |
| Cost               | **$6.64 vs $12.44** (47% reduction)   |
| Time               | **38m vs 64m** (40% reduction)        |
| Terminal-Bench 2.0 | **90.2% (#1)** on Claude Opus 4.7     |

**Two key innovations that directly apply:**

1. **Stem Agent** — A single generic system prompt shared across all phases.
   Role differentiation via **user messages**, not system prompt changes.
   Result: Explore phase's ingested context is a **cache hit** when Plan begins.
   This is exactly the phase-linear plan proposed here, validated in a shipping
   product.
2. **Virtual File System** — Minified file content (whitespace stripped, ~20–50%
   token reduction) during exploration; full byte-exact content during edit phase.
   Matches the "minified reads on Survey/Plan, exact bytes on Implement" split
   (scope item B.4).

**Architecture:** Client-server (`vixd` daemon + `vix` TUI). The daemon handles
LLM interaction and tool execution. Session state under `.vix/` directories.
Not directly forkable (AGPL-3.0 vs Atelier's Apache-2.0/MIT), but architectural
patterns are freely reusable.

### Codex CLI (github.com/openai/codex) — reference cache design

Codex CLI (89K stars, Rust, Apache-2.0) has the most detailed public
documentation of production cache management (Bolin, Jan 2026).

**Key patterns extracted:**

- **`thread_id` as cache key** — Stable thread ID ensures prefix reuse across
  the Responses API. Reference for OpenAI-side caching.
- **Prompt construction layers** — Static content (instructions, tool schemas,
  sandbox) at the front; dynamic content (conversation, new instructions) at the
  back. Exact prefix/tail separation.
- **Automated compaction** — `/responses/compact` endpoint returns a smaller
  representation when token count exceeds threshold.
- **Stateless requests** — Full history on every request (not
  `previous_response_id`), enabling caching + ZDR compliance.
- **Subagent model** — Manager spawns parallel workers, each with its own context
  window.

### Goose (github.com/aaif-goose/goose) — provider-agnostic host

Goose (34K stars, Rust, Apache-2.0, Linux Foundation) is the strongest example
of the "bring your own model + MCP tools" pattern. Converging to a single binary
speaking Agent Client Protocol (ACP). ACP would be the natural wire format for
client ↔ daemon communication if Atelier's CLI grows beyond a single entry point.

### Aider (github.com/Aider-AI/aider) — cache pioneer

Python, Apache-2.0. First coding tool to expose `--cache-prompts` and
`--cache-keepalive-pings`. Key lesson: **keepalive pings** prevent 5-minute TTL
expiry during idle periods in long sessions.

### Supportive projects

| Project                        | Pattern                                               | Relevance                                 |
| ------------------------------ | ----------------------------------------------------- | ----------------------------------------- |
| `alfredcs/stem-agent`          | Academic paper on stem-cell-like agent specialization | Validates the stem concept with citations |
| `masteragentcoder/agentcache`  | Prefix-Preserving Fork + Cache-Safe Compaction        | Algorithm for cache-safe compaction       |
| `OnlyTerp/prompt-cache-skills` | Drop-in cache fixes for 13 harnesses                  | Audits OpenCode's caching gaps            |
| `AtomicBot-ai/atomic-agent`    | KV-cache byte-stable prefix for local models          | Best written stable-prefix contract       |
| `esengine/DeepSeek-Reasonix`   | Two-model Coordinator (separate sessions)             | Alternative when planner ≠ executor model |
| `framersai/agentos`            | `SystemContentBlock` + `cache_control` type support   | API-level cache-control abstraction       |

### Atelier's existing owned-execution plumbing

The MCP server already has **three call paths** through `select_owned_route` +
`execute_owned_prompt`:

1. `tool_agent()` — the `agent` MCP tool
2. `_run_owned_workflow()` — internal workflow execution
3. `_model_recommendation_owned_route()` — model recommendations

The `host_router_bridge.py` module bridges the router to external hosts.
The CLI directory (`gateway/cli/commands/`) already has `savings.py` (1002 lines),
`route.py` (285 lines), `context.py` (placeholder). The build cost is wiring,
not reinvention.

### References

1. **Vix** — github.com/get-vix/vix. AGPL-3.0. Stem agent + virtual file system.
   Benchmarks: 47% cost reduction, 40% time reduction vs Claude Code.
2. **Codex CLI** — github.com/openai/codex. Apache-2.0. Bolin M. "Transparency in
   Prompt Construction for Codex" (Jan 2026), OpenAI Developer Community.
3. **Goose** — github.com/aaif-goose/goose. Apache-2.0, Linux Foundation (AAIF).
   Agent Client Protocol (ACP).
4. **Aider** — github.com/Aider-AI/aider. Apache-2.0. `--cache-prompts`,
   `--cache-keepalive-pings`.
5. **agentcache** — github.com/masteragentcoder/agentcache. Prefix-Preserving
   Fork + Cache-Safe Compaction. 75.8% cache hit rate demonstrated.
6. **prompt-cache-skills** — github.com/OnlyTerp/prompt-cache-skills. Cache
   audits for 13 agent harnesses including OpenCode.
7. **AtomicBot/atomic-agent** — github.com/AtomicBot-ai/atomic-agent.
   `PROMPT.md` stable-prefix contract (KV-cache byte-stable prompt assembly).
8. **DeepSeek-Reasonix** — github.com/esengine/DeepSeek-Reasonix. Two-model
   Coordinator pattern for separate planner/executor sessions.
9. **agentos** — github.com/framersai/agentos. `SystemContentBlock` type with
   `cache_control` support.
10. **STEM Agent** — alfredcs/stem-agent. arXiv:2603.22359. Academic
    formalization of the stem-cell-like agent architecture.
11. **ThunderAgent** — arXiv:2602.13692. Program-aware agentic inference with
    KV-cache optimization (1.5-3.6× throughput improvement).

## Open questions — answered by research

**Transport choice (was open):**
litellm is the right default for broad provider reach (supports `cache_control`
on Anthropic, `prompt_cache_key` on OpenAI-compatible). For pure-Anthropic users
who want 1-hour TTL, provide `--transport anthropic-direct` calling the Messages
API directly, reusing the `stable_prefix` / `dynamic_tail` split.

**Cache TTL (was open):**
5-minute TTL with keepalive pings is the right default for interactive sessions
(lower write cost at 1.25× vs 2×, cache refreshes on every turn). 1-hour TTL is
worth a flag for headless/batch runs. Both Vix and Claude Code use 5-min default.

**Tool-use loop and cache stability (was open):**
All high-cache-hit projects follow one rule: **tool definitions never change
mid-session**. Fixed tool list at startup, byte-stable for the entire run.

**Edit & approvals (was open):**
Reuse existing `tool_supervision` path. Default safety: confirm on destructive
actions unless `--yolo`. Codex's sandbox-per-task is aspirational.

**Multi-provider affinity (was open):**
Switching providers mid-session invalidates the cache. Default: sticky affinity.
Warn when cheaper provider loses more value due to cache eviction.

**Cache-hit rate target:**

- Vix: 60-80%+ cache hit on Plan reading Explore's context.
- agentcache: 75.8% with prefix forks (vs 0% without).
- Industry target: >60% cache read / (cache read + cache write + fresh) sustained.

### Positioning vs Vix

Vix is the closest existing product. The differentiator for Atelier's CLI is:

1. **Existing infrastructure** — owned_execution_lanes, cross-vendor routing,
   compression, dedup, savings reporting, code-intel already exist. Wiring, not
   reinvention.
2. **Host-agnostic** — Works on the same creds regardless of daily driver.
3. **Full cache reporting** — Part 1's savings_summary gives honest per-run
   economics that Vix doesn't surface.
4. **Multi-provider by default** — select_owned_route already routes across
   vendors per-task.

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

| Concern                                       | Existing component to build on                                                                             |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Provider/model selection on user creds        | `owned_execution_routing.select_owned_route`, `detect_api_key_vendors`, `load_route_config_or_default`     |
| Making the API call (own key)                 | `owned_execution_lanes.execute_owned_prompt` (litellm/openai transports)                                   |
| Stable-prefix / dynamic-tail + cache metadata | `owned_execution_lanes` (`stable_prefix_hash`, cache_metadata)                                             |
| Stem agent / phase-linear system prompt       | Concept validated by Vix; build as single generic system prompt, phase differentiation via user messages   |
| Minified reads (Survey/Plan)                  | Vix Virtual File System pattern; Atelier already has compact projection in `atelier_read` outline mode     |
| Cache-safe compaction (fork preserve)         | `agentcache`'s Prefix-Preserving Fork + Cache-Safe Compaction algorithm; Atelier has `context_compression` |
| Cache affinity / warm route                   | `_sticky_affinity_candidate`, `cache_affinity_for_route`, `cache_policy: inherit`                          |
| Compaction when prefix grows too large        | `core/capabilities/context_compression`                                                                    |
| Within-run read dedup                         | `core/capabilities/context_dedup` (Part 1)                                                                 |
| Cost / cache-split reporting                  | `core/capabilities/savings_summary` (Part 1 cache-split + compaction credit)                               |
| Code intel for Survey/Implement               | existing code-intel engine + MCP tool fns                                                                  |
| CLI wiring                                    | `gateway/cli` (keep entry-point logic thin per architecture rules)                                         |
| Cache-keepalive pings                         | Aider's `--cache-keepalive-pings` pattern; run a simple timer ping every 5 min                             |

## Credential model

- User's own keys only, discovered from env / `.env` via `detect_api_key_vendors`
  (and any litellm-compatible base-url/token, e.g. `ANTHROPIC_BASE_URL` +
  `ANTHROPIC_AUTH_TOKEN`, for OpenRouter/Bedrock/Vertex-style setups).
- No key ⇒ the CLI exits with an actionable message (which env vars to set);
  it must never silently route to a transport it cannot execute.
- Keys are read at call time and never persisted by Atelier.

## Milestones (for the implementing agent)

0. **M0 — Research.** Landscape survey (find out all other open source cli tools that atelier could potentially reuse like opencode vix etc do the through research) above. Phase-linear cache-hit
   assumption validated by Vix's production benchmarks:
   - 47% cost reduction vs Claude Code (7-task benchmark)
   - 40% time reduction
   - #1 Terminal-Bench 2.0 at 90.2%
   - Cache hit pattern: 60-80%+ on Plan reading Explore's context
   - Transport: litellm default (`cache_control` + `prompt_cache_key`),
     `--transport anthropic-direct` for pure-Claude / 1-hour TTL
   - TTL: 5-minute default with keepalive pings; `--ttl 1h` flag for headless
1. **M1 — Owned session core.** A drivable owned coding session (single shot)
   on user creds: route → execute → receipt, with stable prefix + one cache
   breakpoint. No phases yet. Reuse `execute_owned_prompt` from MCP server path.
2. **M2 — Phase-linear conversation (stem agent).** Survey/Plan/Implement in one
   byte-stable conversation with generic stem-agent system prompt; per-phase
   user messages for role differentiation. Measured cache-hit on Plan phase.
   Target: >60% cache read ratio.
3. **M3 — Minified reads + dedup + compaction fallback** wired into the read
   path. Reuse Atelier's existing compact projection (outline mode) for
   Survey/Plan reads; full byte-exact reads for Implement. Add cache-safe
   compaction (fork + preserve prefix, don't rebuild).
4. **M4 — CLI surface** (`atelier code`, `resume`, `report`) + credential
   discovery + approvals/cost guardrails + keepalive pings.
5. **M5 — Reporting** parity with Part 1 (cache split, $ vs naive baseline)
   plus per-run receipt with cache-hit ratio and Vix-baseline comparison.

### Cache-hit targets per milestone

| Milestone                | Target cache-read ratio | Notes                                      |
| ------------------------ | ----------------------- | ------------------------------------------ |
| M1 (single shot)         | 0% (no reuse yet)       | Single turn only                           |
| M2 (phase-linear)        | >60%                    | Plan reads Survey context as cache hit     |
| M3 (minified+compaction) | >70%                    | Fewer bytes read = easier prefix stability |
| M4 (CLI surface)         | >70% (same)             | Production hardening                       |
| M5 (reporting)           | >60% sustained          | Full session with keepalive pings          |

## Dependencies

- Part 1 (this PR): `context_dedup`, cache-split reporting, compaction crediting,
  `load_route_config_or_default` / `detect_api_key_vendors`.
  - `docs/plans/phase-linear-cache-reuse[infeasible]` — this plan is its enabler;
    fold its rationale (00) and design-spec (02) in once M2 lands and flip it to
    feasible.
  - Existing owned-execution + cross-vendor routing + context-compression modules.
  - **Research sources:** Vix (github.com/get-vix/vix), Codex CLI engineering blog
    (Bolin, Jan 2026), agentcache PPF/CSC paper, prompt-cache-skills audits,
    AtomicBot stable-prefix contract, Goose ACP spec. All non-Atelier sources are
    pattern references, not code imports.

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

## Open questions — remaining

The original open questions were researched and answered in the Research section
above. What remains open after research:

- **Transport detail:** For `--transport anthropic-direct`, what is the exact
  invocation path and client library? The Anthropic Python SDK directly, or
  a minimal httpx wrapper? Needs a decision during M1.
- **Keepalive mechanism:** Does the keepalive ping go in a background goroutine/
  thread, or does it piggyback on the next user turn? Background is simpler
  but costs an extra API call every 5 min of idle time.
- **Session state persistence format:** JSONL (simplest) vs SQLite (queryable
  for `report` and `resume`). SQLite adds a dependency but enables richer
  reporting; JSONL can always be migrated. Decide in M4.
- **TUI vs line-oriented:** Does M4 need a Bubble Tea / Textual TUI (like Vix's
  `vix` client), or is a line-oriented REPL sufficient for M1–M3 with TUI
  deferred to M6+? Line-oriented is simpler; page output through `$PAGER`.
- **DeepSeek-Reasonix two-model pattern:** For the case where Survey needs a
  different model than Implement (e.g., Sonnet for reading, Opus/Haiku for
  editing), the Coordinator pattern (separate sessions, don't mix prefixes)
  may be better than phase-linear. Is this a flag or a separate mode?
