---
name: perf-review
description: Verify a code change against measured performance gates — latency & tail-latency regression, profiler-confirmed hot paths, memory/leak soak, I/O & wire budgets, and scaling — by running it, not reading it. Enforces performance quality; does not review general code.
---

# Performance review

This skill checks whether a **code change actually meets its performance bar** — it runs the changed surface and gates on **five** objective, _measured_ signals: **latency & throughput** (including the tail, not just the mean), **hot-path truth**, **memory & resource leaks**, **I/O & wire budgets**, and **empirically-verified scaling**. It works in **any language and any project**: discover the repo's _own_ benchmark, profiler, load-generator, query-log, and browser-perf tooling rather than assuming a stack. **It weighs every cost in context** (see Guardrails). It does **not** review general code quality (use `/code-review` for that) and does **not** auto-apply optimizations inline (the engineer owns the fix); on request it **orchestrates** remediation — one solver per blocker, re-measured before merge (step 11).

When invoked, briefly tell the user what you'll measure and that any fixes are opt-in — handed to per-blocker solvers and re-measured before merge — then gather inputs.

## Operating loop

1. **Ground the target and baseline.** Discover the project's _own_ performance tooling before assuming anything — its benchmark runner, profiler, load generator, query log, and (for UI) browser-perf tooling, and how each is normally invoked (look in `CLAUDE.md` / `AGENTS.md`, the README, CI config, and the dependency manifest). Tooling varies by stack: benchmark harnesses such as `pytest-benchmark`, `go test -bench`, `cargo bench` / `criterion`, JMH, `hyperfine`, or a project's own bench suite; profilers such as `cProfile` / `py-spy`, `pprof`, `perf`, `async-profiler`, Instruments, or browser devtools; load/soak tools such as `wrk`, `k6`, `locust`, or `ab`; memory/leak tools such as `tracemalloc`, `memray`, `valgrind`, `heaptrack`, or `/proc` + fd counts. For **page/frontend** surfaces, measure Core Web Vitals (LCP / INP / CLS / TBT) via the project's browser tooling (Lighthouse, Chrome DevTools, Playwright traces) — and if this host provides a dedicated web-performance skill, hand the page-load measurement to it. For what remains unknown, use `AskUserQuestion` in a single call covering all gaps — at minimum: the surface to measure (function / endpoint / request path / page), the baseline (default: the pre-change code via the repo's VCS — a working-tree stash or the parent commit), the thresholds (defaults: **5% wall-time on p50 _and_ p99**, **0 new allocations on the hot path**, **0 net heap/handle growth across the soak**, **0 new queries / round-trips**), the representative workload, the **input sizes** for the scaling curve, and the **soak iteration count**. Confirm exact commands per the side-effect guardrail before running anything.
2. **Establish the baseline.** Measure the _unchanged_ code first (stash the diff or check out the baseline via the repo's VCS). Capture the numbers — the full latency distribution (p50/p95/p99), not just the mean.
3. **Measure the change.** Re-run the identical bench and workload on the changed code, on the same machine with the same inputs and enough iterations to beat noise. Record variance and the distribution, not just a single number.
4. **Gate — latency & throughput.** Compare change vs baseline. A wall-time / throughput delta beyond the threshold _and_ outside the noise band is a **Blocker** — and gate the **tail (p95/p99)**, not only p50: a change that holds the median flat while blowing up p99 still fails. Include **cold-start / warmup / first-call** cost, **time-to-first-byte** for streaming responses, and **latency under representative concurrency** (lock contention and queueing surfaced by the profiler count here). For page surfaces, a regressed Core Web Vital (LCP / INP / CLS) is a **Blocker**.
5. **Gate — hot path.** Profile the change under the workload with the stack's profiler. Confirm the real top cost centers, including **off-CPU / lock-wait** time where the workload is concurrent. A claimed hot path the profiler does not corroborate — or a fix aimed at a path that is not hot — is a **Blocker**. Before calling a cost center _waste_, name the **feature it serves** — work a feature pays for is not waste even when the profiler ranks it high (see Guardrails: product guarantee).
6. **Gate — memory & resource leaks.** Measure peak memory / allocations and **GC pressure** (allocation rate + pause time/frequency) under the workload with the stack's memory/allocation profiler. Then **soak**: run the surface for many iterations and confirm that heap/RSS **and** open file descriptors, sockets, DB connections, and threads return to a flat baseline. **Monotonic growth across iterations is a leak — a Blocker** that a single-shot peak reading cannot catch. Any growth beyond budget is a **Blocker**.
7. **Gate — I/O & wire.** Measure, under the workload: **query count and N+1**, plus the **query plan / index usage** (`EXPLAIN` — one query silently going full-scan is a regression even when the count is unchanged); **cache hit-rate** for caching changes; **syscall / disk-IO volume**; **network round-trips**; and **response payload size / bytes over the wire** (for agent/LLM surfaces, tokens per call/response), plus shipped **artifact / bundle / binary size**. Growth beyond budget is a **Blocker**.
8. **Gate — scaling & worst-case.** Do not infer complexity from a single data point: measure the surface across **growing input sizes** and fit the growth curve. A change that scales **superlinearly where it claimed linear** (or otherwise worse than its stated complexity) is a **Blocker**. Probe **worst-case / adversarial inputs** — data skew, pathological regex / catastrophic backtracking, degenerate or deeply-nested structures; a collapse on a realistic worst case is a **Blocker**.
9. **Critique (advisory only).** Theoretical complexity, micro-optimizations, and "this could be faster" observations with no _measured_ impact are **Warnings** — never blockers. Speculation is not gate-able. A **measured** cost that is immaterial on the real critical path is **also a Warning** — reserve **Blocker** for _material_ costs (see Guardrails: out of budget).
10. **Verdict.** End the review with exactly one fenced JSON block (the final element of the review itself), so a caller can parse it:

```json
{
  "verdict": "NEEDS_FIX",
  "gates": {
    "latency": "fail",
    "hot_path": "pass",
    "memory": "pass",
    "io_wire": "pass",
    "scaling": "pass"
  },
  "baseline": "parent commit (HEAD~1) vs working tree",
  "measurements": {
    "latency": "search() p50 4.1ms -> 6.8ms (+66%), p99 9.0ms -> 31ms (+244%); noise band +/-3%",
    "soak": "1000 iters: RSS flat, fds flat (no leak)",
    "scaling": "fit exponent 1.0 over 4 input sizes (linear, as claimed)",
    "iterations": 200
  },
  "blockers": [
    "search() +66% p50 / +244% p99 wall-time vs baseline (threshold 5%) — the index is re-walked in full on every call instead of reused"
  ],
  "warnings": [
    "a hot-loop allocation in the parser is wasteful but off the measured hot path (0.4% of samples)"
  ],
  "not_checked": [
    "production-scale dataset",
    "sustained concurrent load",
    "cold OS page cache",
    "GC behavior under memory pressure"
  ]
}
```

11. **Remediate (optional, user-gated — never automatic).** A `NEEDS_FIX` verdict hands the fix to the engineer by default. Only if the user opts in (confirm via `AskUserQuestion` after the verdict) do you orchestrate fixes — and even then the reviewer **never hand-edits product code itself**. **You stay the orchestrator**: spawn the solvers yourself with the host's own sub-agent capability and coordinate them directly — you create the worktrees, dispatch each solver, re-measure, and open the PRs. Do **not** hand the whole remediation off to a separate workflow / swarm engine that runs it end-to-end without you; you own the loop. Drive each blocker through its own pipeline, **independently**:
    1. **Isolate.** Create a dedicated **git worktree per blocker** (use the host's worktree / swarm / sub-agent capability if it has one; otherwise `git worktree add`). One finding, one worktree — so fixes can't collide, mask each other, or merge as a bundle the user can't selectively reject.
    2. **Spawn one sub-agent per blocker, yourself.** Using the host's sub-agent tool, launch a separate solver sub-agent for each finding (one per worktree) and orchestrate them directly. Hand each sub-agent _only_ its single finding: the measured evidence (the numbers, the profiler/soak output, the exact cost center) and the minimal-fix hint from the verdict. Do not let one solver fix two findings, and do not widen its scope into a refactor.
    3. **Re-measure _and_ re-verify the feature — don't trust the diff.** When the solver reports done: (a) **re-run that finding's failed gate(s)** in its worktree with the _identical_ harness, workload, inputs, warm/cold state, and iteration count, and confirm the gate now **passes** with no previously-passing gate regressed — measure the _right_ thing (a metric blind to the change, like net-growth for a file **rewrite**, or a workload that never exercises the fix, like a soak below the eviction cap, proves nothing); **and** (b) **re-verify the feature's product guarantee still holds** — a patch that clears the number by degrading freshness, durability, ordering, or accuracy is a **false solution**, not a fix. A patch that doesn't move its gate to `pass`, or that breaks the feature, is not done — send it back or report it unresolved; never merge it.
    4. **Review.** Present each worktree's **before → after numbers** (not just "fixed") to the user, per finding.
    5. **Merge gate.** Merge a worktree to `main` (per the repo's convention — open a PR or merge directly) **only** when (a) its re-run proves the gate cleared on the same workload, (b) the fix **preserves the feature's product guarantee** (no false solution), **and** (c) the user approves that finding's numbers. Discard the worktree on rejection. Merge per-finding so the user accepts or rejects each fix on its own evidence.

## Guardrails

- **Measure, don't eyeball.** Every blocker must cite a number from a run you actually executed, not a guess from reading code. No number → not a blocker.
- **Discover the stack; don't assume it.** Use the project's own benchmark / profiler / load / query-log / browser tooling and conventions. Never hardcode one language's commands — infer them from the repo, or ask. **Never reference another project's internal benchmarks** (this skill runs against the user's repo, not its own home); discover the repo's own tooling every time.
- **Averages lie — gate the tail.** A change can hold p50 flat and blow up p99. Always capture and gate the latency distribution, not just the mean.
- **A leak needs a soak, not a snapshot.** Memory and handle leaks only appear as growth across many iterations — a single peak-memory reading cannot detect one. Run the soak (heap **and** file descriptors / sockets / connections / threads) or set the `memory` gate `skipped` and say so.
- **Verify Big-O by measuring, not reading.** A complexity claim (linear, quadratic→linear) requires at least three growing input sizes and a fitted curve — one data point proves nothing.
- **A green microbenchmark is not a green verdict.** Synthetic benches miss cold cache, real data shapes, concurrency, tail latency, and GC pressure. List what you could not measure in `not_checked` and hand it to a human.
- **A number out of budget is not automatically a Blocker — weigh it against the real critical path.** A microbenchmark breach, or a self-chosen absolute bar exceeded with no baseline, is a _hypothesis_, not a verdict. Put the cost in end-to-end context before gating: µs–ms of per-call framing on a path always followed by seconds of model inference, network I/O, or user think-time is a **Warning**. Reserve **Blocker** for costs that are _material_ — dominant on the critical path, **unbounded / compounding** (a leak, an O(n²), a per-session-growing cost), user-perceptible, or breaching an explicit SLA. Don't manufacture blockers from synthetic bars the real workload never feels.
- **Speed that costs a product guarantee is a regression, not a fix.** Before you flag a hot path _or_ accept a remediation, name what the code is _for_ — much 'overhead' is a feature paying its way: a near-realtime sidecar the UI/statusline reads, a routing/recommendation decision, a durability `fsync`/flush, an ordering guarantee, an audit log, an accuracy computation. A change that clears a perf gate by **batching, deferring, dropping, sampling, or coarsening** work a feature depends on — making a near-realtime signal stale, weakening durability/ordering, or lowering accuracy — is a **false solution**: reject it even though the number improved. State the guarantee the path provides (freshness / visibility-latency, durability, ordering, accuracy, correctness) and prove the fix **preserves** it. If the cost is the genuine price of the feature, the right verdict is _no change_ — or moving the work off the critical path **only if** the guarantee still holds end-to-end.
- **Compare like for like.** Same machine, inputs, iteration count, and warm/cold state for both baseline and change. Report variance and ignore deltas inside the noise band.
- **No baseline, no regression claim.** If you cannot measure the unchanged code, you cannot gate latency, memory, I/O, or scaling against it — set those gates to `skipped` and default the verdict to `NEEDS_FIX`.
- **Remediation is opt-in, orchestrated by you, never inline (see step 11).** One finding → one worktree → one solver, scoped to the minimal fix; re-run the failed gate with the identical harness before merge (reading the diff is not proof — a green re-measure is). Never merge without that proof, the feature's guarantee intact, and the user's approval.
- **Running benches, profilers, load, and soaks is a side-effect.** Confirm the command via `AskUserQuestion` before running it unless the repo already authorizes it.
- **Default to `NEEDS_FIX`.** A `DONE` verdict requires positive proof every gate passed; a skipped gate is not a pass.
