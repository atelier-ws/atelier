# M5 — Expand `ab` benchmark suites

> Risk: Medium. New benchmark code + graders. Independent of M1–M4.

## Problem

The internal A/B harness (`benchmarks/ab/`) advertises savings across multiple
mechanisms in the README (context reuse, compression, failure rescue, loop
detection, routing, tool supervision, outline reads, token-budgeted search) but
ships **one** suite (`suites/long_session.py`) and **one** grader
(`graders/recall_rubric.py`). Headline numbers don't map to runnable suites, so
claims aren't independently reproducible.

## Scope

In:
- Add one suite per advertised savings mechanism that lacks coverage. Each suite
  defines tasks + the expected on/off delta it measures.
- Add graders where `recall_rubric` doesn't fit (e.g. a routing-quality grader,
  a loop-detection grader). Reuse existing stats helpers (Wilson CI already in
  `benchmarks/ab/tests/test_aggregate.py`).
- Each suite ships with a tiny smoke fixture so it runs in CI quickly.

Out:
- SWE-bench / terminalbench changes (those harnesses already exist; M6 handles
  the public results story).

## Files

- `benchmarks/ab/suites/` — new suite modules (model on `long_session.py`).
- `benchmarks/ab/graders/` — new grader modules (model on `recall_rubric.py`).
- `benchmarks/ab/runner.py`, `aggregate.py`, `report.py` — wire new suites in.
- `benchmarks/ab/tests/` — a test per new suite/grader.

## Steps

1. Read `runner.py`, `aggregate.py`, `report.py`, `suites/long_session.py`, and
   `graders/recall_rubric.py` to learn the suite/grader contract.
2. List the README savings mechanisms; map each to an existing suite or a gap.
3. For each gap, add a suite that isolates that mechanism (on vs off) and a
   grader that scores its specific outcome.
4. Add a smoke fixture + a fast test per suite/grader.
5. Register suites so `bench_run.py` can enumerate them.

## Validation

```bash
make lint && make typecheck
uv run pytest benchmarks/ab/tests -q
LOCAL=1 uv run pytest tests/benchmarks/ -v -m ab   # if ab-marked tests apply
```
Run each new suite's smoke fixture end-to-end and confirm it produces a graded
report with a CI-bounded delta.

## Done when

- Every README savings mechanism maps to a runnable `ab` suite + grader.
- Each suite has a fast smoke test; `benchmarks/ab/tests` all pass.
