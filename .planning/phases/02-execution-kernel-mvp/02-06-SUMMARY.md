---
phase: 02-execution-kernel-mvp
plan: 06
subsystem: benchmark-solver
tags: [benchmark-solver, owned-runtime, retry, terminalbench]
requires:
  - phase: 02-execution-kernel-mvp
    provides: Canonical default definitions for owned roles, workflows, solver rules, and reviewer contract.
provides:
  - Structured benchmark solver attempt/run artifacts with JSON and stream-JSON outputs.
  - Harness-feedback retry context built from canonical solver defaults instead of duplicated local prompt text.
  - An opt-in TerminalBench owned-solver provider arm and headless solver CLI surface.
affects: [02-07, phase-3-routing, terminalbench, benchmark-gate]
tech-stack:
  added: []
  patterns:
    - Keep cross-attempt retry state in the benchmark solver runtime instead of trying to force it through intra-workflow `fork_from` outputs.
    - Put event/artifact schemas in core so the CLI and benchmark adapters emit the same structured records.
    - Keep actual step execution injectable for tests, but give the solver a real default runner path through existing host-runner command building.
key-files:
  created:
    - .planning/phases/02-execution-kernel-mvp/02-06-SUMMARY.md
    - src/atelier/core/capabilities/benchmark_solver.py
    - src/atelier/gateway/cli/commands/benchmark_solver.py
    - tests/core/test_benchmark_solver.py
    - tests/benchmarks/test_terminalbench_solver_retry.py
  modified:
    - src/atelier/gateway/cli/commands/benchmark.py
    - benchmarks/terminalbench/agent_adapter.py
    - benchmarks/terminalbench/runner.py
    - benchmarks/terminalbench/tests/test_agent_adapter.py
    - benchmarks/terminalbench/tests/test_runner.py
key-decisions:
  - "The solver runtime owns cross-attempt retry context and artifact/event shaping; only step execution is injected."
  - "TerminalBench keeps `mode` as the on/off arm and adds the owned solver as a separate provider/backend dimension."
  - "The headless solver command lives under `atelier benchmark solver` and uses the existing host-runner command builder for default execution."
patterns-established:
  - "Retry prompts reuse canonical solver rules from the defaults registry and explicitly carry harness feedback plus the prior review verdict."
  - "Owned solver runs emit `start` / `attempt` / `step` / `retry` / `complete` events and persist matching JSON + NDJSON artifacts."
requirements-completed: [EXEC-09, EXEC-10, EXEC-11, EXEC-13, BENC-01, BENC-02]
duration: 29min
completed: 2026-06-03
---

# Phase 2: Plan 06 Summary

**Atelier now has a structured benchmark solver runtime that consumes canonical defaults, emits artifact-backed JSON/stream-JSON runs, retries from harness feedback, and exposes an opt-in TerminalBench owned-solver path without changing the existing benchmark arms.**

## Performance

- **Duration:** 29 min
- **Started:** 2026-06-03T09:05:00Z
- **Completed:** 2026-06-03T09:34:00Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments

- Added `benchmark_solver.py` with structured `HarnessFeedback`, `SolverStepArtifact`, `BenchmarkAttempt`, `SolverEvent`, and `SolverRunArtifact` models plus canonical retry-context generation and JSON/NDJSON artifact writing.
- Wired the solver runtime to consume `owned-benchmark-solver`, `terminalbench-owned-solver`, the shared stem prompt, and the reviewer contract from `default_definitions.py` instead of restating prompt/rule text locally.
- Added a headless `atelier benchmark solver` command that can emit human text, JSON, or stream-JSON records and uses the existing host-runner command builder for default execution.
- Extended the benchmark CLI so TerminalBench accepts an opt-in `owned` provider/backend while preserving the existing `claude` and `ollama` arms.
- Added an `AtelierOwnedSolverAgent` TerminalBench adapter that runs the headless solver command inside the benchmark container and guards against meaningless `provider=owned, mode=off` combinations.
- Added focused solver/runtime tests plus TerminalBench selection coverage, while keeping the Docker-backed benchmark tests skip-safe when the external `terminal_bench` package is unavailable in the local repo env.

## Files Created/Modified

- `src/atelier/core/capabilities/benchmark_solver.py` - Owns retry context, attempt/run artifact models, event schema, workflow execution orchestration, and artifact writers.
- `src/atelier/gateway/cli/commands/benchmark_solver.py` - Adds the headless `atelier benchmark solver` command and output-format handling.
- `src/atelier/gateway/cli/commands/benchmark.py` - Registers the solver command and exposes the `owned` TerminalBench provider choice.
- `benchmarks/terminalbench/agent_adapter.py` - Adds the owned solver agent arm, provider field in adapter results, and owned-provider guardrails.
- `benchmarks/terminalbench/runner.py` - Threads the provider dimension through transcript filenames, JSONL rows, and CLI choice parsing.
- `tests/core/test_benchmark_solver.py` - Covers retry-context generation, retry attempts, artifact writing, and CLI JSON/stream-JSON output.
- `tests/benchmarks/test_terminalbench_solver_retry.py` - Covers provider selection and owned-provider mode guardrails.
- `benchmarks/terminalbench/tests/test_agent_adapter.py` - Extends adapter schema/owned command expectations when the external benchmark package is installed.
- `benchmarks/terminalbench/tests/test_runner.py` - Updates transcript naming/schema expectations for the provider dimension when the external benchmark package is installed.

## Decisions Made

- Kept the cross-attempt fork/retry logic inside the solver runtime instead of trying to overload `workflow_runner`'s existing step-output `fork_from` semantics.
- Put the event schema in core so both the CLI and TerminalBench adapter can emit the same records without format drift.
- Treated the owned solver as a provider/backend choice rather than a new benchmark mode, so the existing `on` / `off` experiment-arm meaning stays intact.

## Deviations from Plan

### Auto-fixed Issues

**1. [Execution path] Added a real default host-runner-backed step executor instead of leaving the solver runtime test-only**
- **Found during:** Post-test implementation review
- **Issue:** The first runtime draft only worked with injected step executors, which made the headless CLI usable in tests but not in a real run.
- **Fix:** Added a default executor built on `resolve_swarm_runner_command()` so the headless solver command can actually drive a selected runner profile by default.
- **Files modified:** `src/atelier/core/capabilities/benchmark_solver.py`, `src/atelier/gateway/cli/commands/benchmark_solver.py`

**2. [Benchmark dimension] Separated owned execution into the provider/backend dimension instead of overloading the benchmark mode**
- **Found during:** Pre-implementation design critique
- **Issue:** Reusing `mode` for the owned solver would have conflated the on/off experiment arm with the execution backend.
- **Fix:** Added an `owned` provider/backend path while leaving `mode` as the on/off benchmark arm.
- **Files modified:** `benchmarks/terminalbench/agent_adapter.py`, `benchmarks/terminalbench/runner.py`, `src/atelier/gateway/cli/commands/benchmark.py`

## Issues Encountered

- The local repository environment does not currently include the external `terminal_bench` package, so the Docker-backed adapter/runner tests were made explicitly skip-safe instead of failing the focused gate.
- TerminalBench benchmark helpers use a package layout that is awkward inside the repo checkout, so the benchmark tests now insert the local `benchmarks/` path before importing the `terminalbench` package.

## User Setup Required

The owned solver path assumes the selected runner CLI is available in the execution environment. No additional configuration is needed for the focused test suite.

## Next Phase Readiness

Phase `02-07` can now focus purely on cheaper read-time context because the owned workflow/default/solver pieces are in place and Phase 2's remaining scope is isolated to the structural minify reader path.

---
*Phase: 02-execution-kernel-mvp*
*Completed: 2026-06-03*
