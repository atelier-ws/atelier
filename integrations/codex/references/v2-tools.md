# Atelier V2 MCP Tools (reference)

V2 adds reasoning-state, environment, monitor, savings, and smart-tool
capabilities. All V1 tools listed in [workflow.md](workflow.md) remain
available and **backward compatible**.

## Run ledger (per-run reasoning state)

- `atelier_get_run_ledger({ run_id })` — returns the current plan,
  hypotheses tried/rejected, verified facts, open questions, blockers,
  next required validation, tool/token counts, file/command/test
  history, and the recent event tail.
- `atelier_update_run_ledger({ run_id, op, ... })` — append-only
  setters: `set_plan`, `add_hypothesis` (with optional `rejected`),
  `add_verified_fact`, `add_open_question`, `set_blocker`,
  `set_next_validation`, `record_test`.

Use these instead of restating prior reasoning in chat.

## Monitors

- `atelier_monitor_event({ run_id, event })` — pushes a structured
  observation (tool result, command outcome, file edit). Returns any
  monitor alerts (`SecondGuessing`, `Thrashing`, `BudgetExhaustion`,
  `RepeatedFailure`, `WrongDirection`, `OffPlan`, `WrongTool`,
  `ContextRot`).

## Context compression

- `atelier_compress_context({ run_id })` — returns a stable summary of
  the run for re-injection when the live tool log gets long. Replaces
  noisy event scrolls.

## Environments

- `atelier_get_environment({ id })` — full Environment definition.
- `atelier_get_environment_context({ domain })` — auto-resolves the
  environment by domain prefix and returns rules, forbidden phrases,
  required validations, attached procedures.

## Smart tools (default-on cache)

- `atelier_smart_read({ path, max_bytes? })` — caches reads and tracks
  per-call savings.
- `atelier_smart_search({ pattern, path? })` — caches FTS hits.
- `atelier_cached_grep({ pattern, path?, args? })` — wraps `grep`/`rg`
  with caching and command-injection rejection.

These are default-on Atelier augmentations for bounded, repeated context
reads/searches. Native `Read`, shell `rg`, `grep`, and direct repository search
remain available when exact raw output is needed. Set
`ATELIER_CACHE_DISABLED=1` to bypass Atelier caching.

## Hard rules (additive to workflow.md)

6. Do not omit `atelier_get_run_ledger` when resuming a run mid-stream.
7. Do not store hidden chain-of-thought in
   `atelier_update_run_ledger` payloads — only observable facts.
8. Do not remove host-native read/search tools; smart tools are an augmentation,
   not a replacement.
