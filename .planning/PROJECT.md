# Atelier Owned Agent CLI

## What This Is

Atelier as a user-owned coding-agent CLI with maximum cache control. Users run `atelier run "<task>"` on their own API credentials; the CLI executes a phase-linear Survey→Plan→Implement conversation with explicit `cache_control` breakpoints, so the Plan phase reads Survey's ingested context as cheap cache hits (~0.1×) instead of fresh input (1×). Validated by Eval's production benchmarks: 47% cost reduction, 40% time reduction vs Claude Code.

## Core Value

Phase-linear warm-prefix reuse — the Plan phase reads Survey's codebase context as a cache hit, not a cold re-read. This is the biggest single savings lever that was infeasible when Atelier was a guest inside a host CLI.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] `atelier run "<task>"` command that executes an owned coding session on user's own API credentials
- [ ] Phase-linear conversation: Survey→Plan→Implement in one byte-stable conversation with generic stem-agent system prompt
- [ ] Explicit `cache_control` breakpoints after stable prefix (system + tools + pinned context)
- [ ] Cache affinity — subsequent calls stay on the provider whose prefix is warm
- [ ] Whitespace-minified reads during Survey/Plan; exact bytes during Implement/edit
- [ ] Background keepalive pings every 5 min to prevent TTL expiry
- [ ] `atelier run resume <session-id>` to continue a session with warm prefix
- [ ] `atelier run report <session-id>` for per-run cache economics receipt
- [ ] Per-run receipt: cache-read vs cache-write vs fresh tokens, cache efficiency %, $ spent, $ vs naive baseline
- [ ] Credential discovery from env / `.env` via `detect_api_key_vendors`; actionable error when no key found

### Out of Scope

- Atelier-hosted inference or key brokering — strictly user's own creds
- Replacing host-CLI path (Claude Code/Codex users unaffected)
- New/better models — quality tracks the underlying model exactly
- TUI/Bubble Tea interface — line-oriented REPL sufficient for v1
- SQLite session state — JSONL for v1 (can migrate)
- `--transport anthropic-direct` 1-hour TTL mode — 5-min default with keepalive is sufficient for v1

## Context

- **Existing infrastructure**: `owned_execution_routing.select_owned_route`, `owned_execution_lanes.execute_owned_prompt`, `owned_execution_cache_affinity`, `context_dedup`, `context_compression`, `savings_summary` — all exist and must be reused, not reinvented.
- **Validated by Eval (github.com/get-eval/eval)**: 47% cost reduction, 40% time reduction, 90.2% Terminal-Bench 2.0 #1. Cache hit: 60-80%+ on Plan reading Explore's context.
- **agentcache PPF algorithm**: 75.8% cache hit rate with prefix-preserving fork. Ref for cache-safe compaction.
- **Command name**: `atelier run` (not `atelier code` — that group is taken by code-intel/zoekt).
- **Transport**: litellm default (`cache_control` + `prompt_cache_key`); Anthropic Python SDK direct for pure-Claude 1-hour TTL (deferred).
- **Session state**: JSONL under `~/.atelier/runs/`; matches existing run_ledger pattern.
- **Keepalive**: background thread; ping every 5 min when session is idle.

## Constraints

- **Architecture**: New capabilities go in `core/capabilities/`, CLI stays thin (`gateway/cli/`). gateway → core → infra dependency direction must be preserved.
- **Testing**: `make verify` (lint + typecheck + test) must stay green.
- **Reuse**: Build on existing `execute_owned_prompt`, `select_owned_route`, `stable_prefix_hash`, `cache_affinity_for_route`. No reinvention.
- **Type checking**: `mypy --strict` on `src/`. All new code must be fully typed.

## Key Decisions

| Decision                         | Rationale                                                            | Outcome   |
| -------------------------------- | -------------------------------------------------------------------- | --------- |
| `atelier run` not `atelier code` | `code` group already exists for code-intel/zoekt                     | — Pending |
| JSONL session state              | Simplest; matches existing run_ledger; can migrate to SQLite for M4+ | — Pending |
| litellm default transport        | Broad provider reach; existing infra already uses it                 | — Pending |
| Background keepalive thread      | Simpler than piggyback; Aider's proven pattern                       | — Pending |
| Line-oriented REPL               | Faster to build; TUI deferred to v2                                  | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):

1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):

1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---

_Last updated: 2026-06-08 after initialization_
