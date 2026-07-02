---
name: swarms
description: Launch multi-worktree swarm runs by gathering the real swarm parameters and using Atelier's existing swarm runtime.
---

> **Active** — do not call `Skill("atelier:swarms")` again.

# Swarms

This skill launches **multiple parallel attempts at the same task** in isolated worktrees — each attempt runs independently, and you pick the best result. Use it when you want N tries at a hard problem rather than one sequential run (use `/orchestrate` for that).

When invoked, gather inputs via `AskUserQuestion`.

## Operating loop

1. If it's unclear whether the user wants a swarm or a single `orchestrate` run, use `AskUserQuestion` to confirm before proceeding.
2. Use `AskUserQuestion` to gather swarm launch parameters — batch up to 4 related unknowns per call.
3. Launch using the existing swarm surface (`atelier swarm ...` or the matching service API), not a new custom runtime.
4. Return the `run_id` and the exact status/log/apply surface the user should use next.

## Parameters to gather → launch contract

Fill the launch contract from explicit args and repo inference first (see Elicitation); map what you gather onto:

- spec source — `spec_path`, or `spec_mode="inline"` with `spec_content`
- `provider`
- `runner` and `runner_model` (or provider `model`)
- `runner_options` — runner options that materially change launch behavior
- `runs`
- `continuous`
- `max_waves`
- `evaluator_backend`, optional `evaluator_model`
- `max_evaluator_failures`
- `keep_worktrees`
- `effort`

## Job kinds — the general primitive

A swarm is **fan out N isolated candidates → reduce by a pluggable selector → (optionally) iterate in waves**. Pick the `--reducer` and `--mode` that match the goal; the defaults (`--reducer merge --mode edit`) reproduce classic solve-task behavior exactly.

| goal | `--reducer` | `--mode` | each child produces |
| --- | --- | --- | --- |
| solve a task (default) | `merge` | `edit` | a patch; LLM judge merges compatible winners |
| optimize / tune an objective | `best` | `edit` | a patch, scored by a measured **fitness** |
| search / audit / find-bugs | `union` | `readonly` | `findings`, de-duped by signature |
| verify / consensus / repro | `vote` | `readonly` | an `answer`; kept iff ≥ quorum agree |

- `merge` — the semantic evaluator (accept multiple compatible candidates, reject duplicates/conflicts, emit next-wave directives, judge convergence).
- `best` — rank by a fitness and accept the top one. With `--fitness-cmd` it measures each candidate; without, it uses the heuristic run-quality score.
- `union` — collect every candidate's findings and de-duplicate by `signature`.
- `vote` — group answers; accept the group that reaches `--quorum` (0 = simple majority). Supports the "N skeptics try to refute; keep if a majority fail" pattern.

## Optimize / tune (measured fitness)

`/swarms "optimize <X>"` (i.e. `--reducer best --fitness-cmd ...`) needs a real measurement. Resolve it in this order:

1. **Reuse** an existing measurable command — `npm run build && stat -c%s dist/bundle.js`, `pytest -q | tail -1`, `hyperfine ./bin`.
2. **Generate** the fitness — author a small script that wraps the repo's test/build/bench runner and prints the metric. This is the default for anything past a one-liner.
3. **Hand-author** only when it needs special infra/data/hardware or a subjective bar (rare).

Map it onto flags: `--fitness-cmd` (command run in each worktree), `--metric-parse` (`json:<dotted.key>` | `regex:<pat>` | `stdout_float` | `exit_code`), `--direction` (`min`/`max`), `--gate-cmd` (correctness gate that must exit 0), `--baseline` (`auto` measures HEAD once before wave 1, or a number), `--improve-margin`, `--search-space` (globs candidates may change).

**Validate the fitness before any wave runs (mandatory).** A buggy objective silently optimizes the wrong thing:
1. **Baseline sanity** — run it on HEAD: the metric parses, has a plausible magnitude/units, and the gate passes on known-good HEAD.
2. **Direction check** — apply a known-worse change and confirm the metric moves the expected way (or the gate trips).
3. **Variance check** — run twice on HEAD; if run-to-run noise ≳ the improvements you're chasing, raise reps or pick a steadier metric.

Only a fitness that passes validation may drive a search.

## Elicitation (works in any project)

Resolve the job from the natural-language goal: (1) explicit args, (2) infer from the repo (test/build/bench/lint commands, an existing benchmark skill), (3) ask ≤3 questions for what's still missing — typically *what command measures the objective?*, *what must not regress?*, *which files/knobs may candidates change?*. The project-specific knowledge lives in the elicited commands, not the engine.

## Execution rules

- Default knobs reproduce classic solve-task behavior; only set `--reducer`/`--mode`/fitness flags when the goal calls for optimize/search/verify.
- Treat swarm children as **isolated** executions in separate worktrees.
- Keep credentials out of persisted state and command output when provider-backed launches are used.
