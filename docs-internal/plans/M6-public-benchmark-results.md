# M6 — Reproducible public results + regression gate

> Risk: Medium. Touches CI + published claims. Depends on M5.

## Problem

`docs/plans/public-benchmarks/index.md` is effectively empty, and committed
SWE-bench / terminalbench outputs are smoke-scale only. There is no published,
auditable results document and no CI gate that fails on a savings/quality
regression. So benchmark numbers can't be cited with confidence and can drift.

## Scope

In:
- A committed `RESULTS.md` (under `docs/plans/public-benchmarks/` or
  `benchmarks/`) with, per benchmark:
  - exact harness + corpus version / commit SHA,
  - baseline vs Atelier deltas with Wilson confidence intervals,
  - a single copy-paste reproduction command.
- A regression-gate CI job that replays a fixed corpus
  (`routing_replay_bench`, `savings_replay`, or the M5 `ab` smoke suites) and
  **fails** if savings% or routing-quality drops below a recorded threshold.
- A real SWE-bench Lite (or Verified subset) run, with a cost/accuracy frontier
  artifact committed, replacing the current smoke-only outputs.

Out:
- New benchmark mechanisms (that was M5).

## Files

- `docs/plans/public-benchmarks/index.md` + new `RESULTS.md`.
- `benchmarks/swe/` (`atelier_proxy.py`, `make_preds.py`, `run_eval.sh`,
  `report.py`) — for the Lite/Verified run.
- `benchmarks/ab/publish.py`, `report.py` — reproduction command + report
  assembly (`_reproduce_sh`, `assemble_post` already exist — reuse).
- `.github/workflows/` — new `benchmark-regression.yml` (scheduled +
  `workflow_dispatch`).

## Steps

1. Pick the regression corpus: smallest fixed set that meaningfully covers
   savings + routing (favor the M5 smoke suites + `routing_replay_bench`).
2. Record current numbers as the baseline thresholds (with CIs).
3. Write `benchmark-regression.yml` to replay that corpus and assert numbers
   stay within threshold; fail otherwise.
4. Run SWE-bench Lite (or a defined subset) via `benchmarks/swe/`; commit the
   preds + a frontier (cost vs accuracy) artifact.
5. Assemble `RESULTS.md` using existing `publish.py`/`report.py` helpers so the
   reproduction command is generated, not hand-written.
6. Fill in `public-benchmarks/index.md` to point at `RESULTS.md`.

## Validation

```bash
make lint && make typecheck
uv run pytest benchmarks/ab/tests/test_publish.py benchmarks/ab/tests/test_report.py -q
```
Dry-run the regression workflow locally; confirm it passes at baseline and fails
when a threshold is artificially tightened. Confirm the `RESULTS.md`
reproduction command actually reproduces the quoted numbers from a clean
checkout.

## Done when

- `RESULTS.md` exists with versioned, CI-bounded, reproducible numbers.
- A scheduled CI job fails on savings/routing regression.
- SWE-bench Lite/subset run + frontier artifact committed (no longer smoke-only).
