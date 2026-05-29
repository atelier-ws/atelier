# M1 — Lint rules + nightly coverage floor

> Risk: Low. No runtime behavior change. Prevents future backsliding on M2/M3.

## Problem

Two classes of debt can grow silently today because nothing gates them:

- Silent error swallowing (`except Exception: pass`) — 28 sites, no lint rule.
- Stray `print()` in `src/` — 132 sites; in MCP stdio modules these corrupt
  protocol framing.

Separately, coverage is computed (`make test-cov`) but **not gated**: CI runs
`make test` with `-m "not slow"` and no `--cov-fail-under`, so slow tests never
run in CI and coverage can regress unnoticed.

## Scope

In:
- Enable ruff `BLE001` (blind-except) and `T20` (flake8-print) rules.
- Add per-directory ignores so existing violations don't block CI immediately
  (they are burned down in M2/M3). Use ruff `per-file-ignores`, not blanket
  disables — the point is to stop *new* violations.
- Add a scheduled (nightly) GitHub workflow that runs the **full** suite
  including `slow` tests with `--cov-fail-under=<measured floor>`.

Out:
- Fixing the existing 28 / 132 violations (that's M2 and M3).
- Changing the fast PR `make test` path (keep it fast, `-m "not slow"`).

## Files

- `pyproject.toml` — `[tool.ruff.lint]` select + `per-file-ignores`.
- `.github/workflows/` — new `nightly-coverage.yml` (model on `tests.yml`).
- `Makefile` — confirm/extend `test-cov` target; add a `test-full` target that
  runs slow tests with coverage.

## Steps

1. Measure the real coverage floor first:
   ```bash
   uv run pytest --cov=atelier --cov-report=term-missing
   ```
   Record the total %. Set `--cov-fail-under` ~2 points below it to start.
2. In `pyproject.toml`, add `BLE` and `T20` to the ruff `select` list.
3. Run `make lint` to enumerate violations. Add `per-file-ignores` entries for
   the currently-offending files only (capture the list — M2/M3 consume it).
4. Add `nightly-coverage.yml`: `schedule:` cron + `workflow_dispatch:`, runs
   `make test-full` (full suite incl. `slow`) with the coverage floor.
5. Add `test-full` to the Makefile if absent.

## Validation

```bash
make lint            # passes with new rules + per-file-ignores
make typecheck
make test            # fast path unchanged
uv run pytest --cov=atelier --cov-fail-under=<floor>   # local dry-run of nightly
```
Confirm `nightly-coverage.yml` parses: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/nightly-coverage.yml'))"`.

## Done when

- New `BLE001`/`T20` violations fail `make lint`; existing ones are tracked in
  `per-file-ignores` (the M2/M3 worklist).
- A nightly workflow exists that runs the full suite with a coverage floor.
