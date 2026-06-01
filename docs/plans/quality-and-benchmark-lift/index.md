# Quality & Benchmark Lift

> Status: **Active** — created 2026-05-29.
> Owner: unassigned.
> Source: repo review (coding quality + benchmark credibility).

## North star

Two outcomes, pursued together:

1. **Coding quality** — remove the structural debt that an agent runtime can least
   afford: god-objects, silent error swallowing, and stray stdout writes that
   corrupt MCP framing.
2. **Benchmark credibility** — turn the broad-but-shallow benchmark infra into a
   reproducible, regression-gated story that backs every savings claim in the
   README.

Every milestone below is self-contained: a subagent can pick up one milestone
file, execute it, validate it, and stop. Milestones are ordered by
risk/leverage — do M1/M2 first (cheap, prevent backsliding), then the
structural and benchmark work.

## Milestones

| ID | File | Title | Risk | Depends on |
|----|------|-------|------|-----------|
| M1 | [`M1-lint-and-coverage-gates.md`](M1-lint-and-coverage-gates.md) | Lint rules (`BLE001`, `T20`) + nightly coverage floor | Low | — |
| M2 | [`M2-silent-except-audit.md`](M2-silent-except-audit.md) | Audit & fix `except Exception: pass` sites | Low | M1 |
| M3 | [`M3-stdout-to-logging.md`](M3-stdout-to-logging.md) | Replace stray `print()` with logging | Low | M1 |
| M4 | [`M4-cli-decomposition.md`](M4-cli-decomposition.md) | Split `cli/app.py` god-object into a commands package | High | M3 |
| M5 | [`M5-ab-suite-expansion.md`](M5-ab-suite-expansion.md) | Expand `ab` suites to cover each savings mechanism | Med | — |
| M6 | [`M6-public-benchmark-results.md`](M6-public-benchmark-results.md) | Reproducible `RESULTS.md` + regression-gate CI | Med | M5 |

## Baseline measurements (captured 2026-05-29)

Re-measure before claiming a milestone done; these are the starting numbers.

| Signal | Value | Command |
|--------|-------|---------|
| `except Exception: pass` | 28 | `grep -rn -A1 "except Exception" src --include='*.py' \| grep -c pass` |
| `except Exception` total | 337 | `grep -rn "except Exception" src --include='*.py' \| wc -l` |
| `print(` in `src/` | 132 | `grep -rn "print(" src --include='*.py' \| wc -l` |
| `cli/app.py` LOC | 9309 | `wc -l src/atelier/gateway/cli/app.py` |
| `cli/app.py` defs | 393 | `grep -cE "^\s*def \|^\s*async def " src/atelier/gateway/cli/app.py` |
| `ab` suites | 1 | `ls benchmarks/ab/suites/*.py` |
| `ab` graders | 1 | `ls benchmarks/ab/graders/*.py` |

## Global validation

Every milestone ends with at minimum:

```bash
make lint && make typecheck && make test
```

Milestones that touch hooks, MCP handlers, or the CLI add the surface-specific
checks from the "Validation by Change Surface" table in `CLAUDE.md`.

## Open questions

- Coverage floor: pick a starting `--cov-fail-under` from the first measured
  full-suite run (M1), then ratchet up. Do not guess a number before measuring.
- M4 sequencing: decompose by command-group; one PR per group keeps review
  tractable and lets subagents run in parallel without colliding.
