---
name: swarms
description: Launch multi-worktree swarm runs by gathering the real swarm parameters and using Atelier's existing swarm runtime.
---
# Swarms

Use this skill when the user wants multiple isolated attempts running in parallel, not a single `orchestrate` run.

## Operating loop

1. Confirm that the user actually wants a swarm and not a single `orchestrate` run.
2. Gather the swarm launch parameters one question at a time.
3. Launch using the existing swarm surface (`atelier swarm ...` or the matching service API), not a new custom runtime.
4. Return the `run_id` and the exact status/log/apply surface the user should use next.

## Parameters to gather

Ask for the real runtime knobs, one at a time, until you have enough to launch:

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
