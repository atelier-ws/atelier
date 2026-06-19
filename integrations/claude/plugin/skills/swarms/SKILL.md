---
name: swarms
description: Launch multi-worktree swarm runs by gathering the real swarm parameters and using Atelier's existing swarm runtime.
---
# Swarms

This skill launches **multiple parallel attempts at the same task** in isolated worktrees — each attempt runs independently, and you pick the best result. Use it when you want N tries at a hard problem rather than one sequential run (use `/orchestrate` for that).

When invoked, tell the user: "I'll spin up multiple isolated attempts running in parallel. Let me confirm a few parameters before launching." Then gather inputs via `AskUserQuestion`.

## Operating loop

1. If it's unclear whether the user wants a swarm or a single `orchestrate` run, use `AskUserQuestion` to confirm before proceeding.
2. Use `AskUserQuestion` to gather swarm launch parameters — batch up to 4 related unknowns per call.
3. Launch using the existing swarm surface (`atelier swarm ...` or the matching service API), not a new custom runtime.
4. Return the `run_id` and the exact status/log/apply surface the user should use next.

## Parameters to gather

Ask for the real runtime knobs via `AskUserQuestion` (batch up to 4 per call) until you have enough to launch:

- spec source: existing `spec_path` or inline `spec_content`
- runner and runner model (or provider model)
- `runs`
- `continuous`
- `max_waves`
- `evaluator_backend`
- optional `evaluator_model`
- `max_evaluator_failures`
- `keep_worktrees`
- `effort`
- any runner options that materially change launch behavior

## Current runtime mapping

Map your conversation directly onto the existing swarm launch contract:

- `spec_path` or `spec_mode="inline"` with `spec_content`
- `provider`
- `runner`
- `runner_model` or provider `model`
- `runner_options`
- `runs`
- `continuous`
- `max_waves`
- `evaluator_backend`
- `evaluator_model`
- `max_evaluator_failures`
- `keep_worktrees`
- `effort`

## Execution rules

- Prefer the repo's existing swarm CLI/API surfaces over inventing new ones.
- Treat swarm children as **isolated** executions in separate worktrees.
- Keep credentials out of persisted state and command output when provider-backed launches are used.
- If the user only needs one coordinated run, route them to `orchestrate` instead of launching a swarm.
