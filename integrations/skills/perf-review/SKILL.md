---
name: perf-review
description: Verify a code change's runtime performance against objective, measured gates — benchmark regression vs a baseline, profiler-confirmed hot paths, and allocation/query budgets — by actually running the code, not reading it. Enforces performance quality; does not redesign or auto-optimize.
---

# Performance review

This skill checks whether a **code change actually meets its performance bar** — it runs the changed surface and gates on three objective, *measured* signals: regression vs a baseline (benchmark delta), hot-path truth (profiler-confirmed cost centers), and resource budgets (allocations, memory, query/IO counts). It does **not** review general code quality (use `/code-review` for that) and does **not** author or auto-apply optimizations (the engineer owns the fix).

When invoked, tell the user in plain English: "I'll measure the changed surface — benchmark it against a baseline, profile it under a realistic workload, and check allocation/query budgets — then gate on the numbers. I need to know what to measure and a few other things first." Then gather inputs.

## Operating loop

1. **Ground the target and baseline.** Infer from the repo what you can (the bench command — e.g. `pytest-benchmark` or `benchmarks/codebench`; the profiler; the workload). For what remains unknown, use `AskUserQuestion` in a single call covering all gaps — at minimum: the surface to measure (function / endpoint / CLI path), the baseline (default: the pre-change code via `git stash` of the working tree, or the parent commit), the regression threshold (default **5% wall-time**, **0 new allocations on the hot path**), and the representative workload / input size. Before running benches, profilers, or starting the app, confirm the command via `AskUserQuestion` unless the repo's `CLAUDE.md` or an allow-rule already authorizes it (this repo authorizes `uv run pytest`).
2. **Establish the baseline.** Measure the *unchanged* code first (stash the diff or check out the baseline). Capture the numbers. If you cannot get a baseline, say so — the regression gate cannot run.
3. **Measure the change.** Re-run the identical bench and workload on the changed code, on the same machine with the same inputs and enough iterations to beat noise. Record variance.
4. **Gate — regression.** Compare change vs baseline on the bench. A wall-time / throughput delta beyond the threshold *and* outside the noise band is a **Blocker**.
5. **Gate — hot path.** Profile the change under the workload (`cProfile` / `py-spy` for Python; stack-appropriate tooling elsewhere). Confirm the real top cost centers. A claimed hot path the profiler does not corroborate — or a fix aimed at a path that is not hot — is a **Blocker**.
6. **Gate — resource budget.** Measure allocations / peak memory (`tracemalloc`) and query / IO counts (N+1) under the workload. Growth beyond budget is a **Blocker**.
7. **Critique (advisory only).** Theoretical complexity, micro-optimizations, and "this could be faster" observations with no *measured* impact are **Warnings** — never blockers. Speculation is not gate-able.
8. **Verdict.** End with exactly one fenced JSON block as the final element, so a caller can parse it:

```json
{"verdict": "NEEDS_FIX",
 "gates": {"regression": "fail", "hot_path": "pass", "resource": "pass"},
 "baseline": "git stash (working tree vs HEAD)",
 "measurements": {"bench": "recall.query p50 4.1ms -> 6.8ms (+66%, noise band +/-3%)", "iterations": 200},
 "blockers": ["recall.query +66% wall-time vs baseline (threshold 5%) — ann_graph.search re-walks the full edge list per call"],
 "warnings": ["dict comprehension in tokenize() is allocation-heavy but off the hot path (0.4% of samples)"],
 "not_checked": ["concurrent load", "cold-cache first call", "production-scale corpus", "peak RSS under sustained traffic"]}
```

## Guardrails

- **Measure, don't eyeball.** Every blocker must cite a number from a run you actually executed, not a guess from reading code. No number → not a blocker.
- **A green microbenchmark is not a green verdict.** Synthetic benches miss cold cache, real data shapes, concurrency, and GC pressure. List what you could not measure in `not_checked` and hand it to a human.
- **Compare like for like.** Same machine, inputs, iteration count, and warm/cold state for both baseline and change. Report variance and ignore deltas inside the noise band.
- **No baseline, no regression claim.** If you cannot measure the unchanged code, you cannot gate regression — set that gate to `skipped` and default the verdict to `NEEDS_FIX`.
- **Verify, don't optimize.** Report the confirmed hot path and the minimal targeted fix. Do not refactor, rewrite, or auto-apply optimizations — that is the engineer's call.
- **Running benches and profilers is a side-effect.** Confirm the command via `AskUserQuestion` before running it unless the repo already authorizes it.
- **Default to `NEEDS_FIX`.** A `DONE` verdict requires positive proof every gate passed; a skipped gate is not a pass.
