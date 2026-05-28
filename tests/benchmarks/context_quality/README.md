# Context Quality Benchmarks

Internal evaluation suite for the Context Quality Lift milestones (v0.2).
These benchmarks run against a real Atelier installation and require:
- A git repository indexed by `code op="search"` (for M1)
- A working Atelier MCP server (for M2–M4)
- Python ≥ 3.12 in the atelier venv

## Protocol

All benchmarks follow this structure:
1. **Seed** — set up the evaluation fixture (real git repo, pre-seeded commit chunks, etc.)
2. **Run** — call the Atelier capability under test for each query/task
3. **Grade** — compare result against ground truth; score 1 (correct) or 0 (incorrect)
4. **Report** — print per-query verdict + aggregate pass rate

Benchmarks are NOT in the normal pytest suite (they are `@pytest.mark.slow`).
Run them explicitly:

```bash
uv run pytest tests/benchmarks/context_quality/M1_lineage.py -v -m slow
```

## Benchmark Targets

| Milestone | File | Target | Baseline |
|-----------|------|--------|----------|
| M1 — Context Lineage | `M1_lineage.py` | ≥7/10 | ≤2/10 |
| M2 — Cache-Aware Routing | `M2_routing.py` | ≥10% cost reduction | — |
| M3 — Counterexample Loop | `M3_verification.py` | ≥60% self-correction | ≤15% |
| M4 — Scoped Pull Context | `M4_scoped.py` | precision ≥0.6 recall ≥0.85 | — |

## Scoring

Each query is graded binary: 1 = correct citation/answer, 0 = wrong/hallucinated.
Pass rate = sum(scores) / len(queries).

**Citation correctness for M1:** A result is scored 1 if the top-ranked commit chunk
returned by `code op="search"` has a `commit_sha` matching the expected SHA **or**
the summary text contains at least 2 of the expected keywords from the ground truth.
Exact SHA match is preferred; keyword fallback handles SHA abbreviation differences.

## Adding New Benchmark Queries

1. Find a real commit in the target repo that fixes a concrete, named bug.
2. Formulate a natural-language query that a developer would ask about that bug.
3. Add an entry to the `QUERIES` list with `sha`, `query`, and `keywords` fields.
4. Run `uv run pytest M1_lineage.py -v -m slow` and verify ≥7/10 pass.

## CI Integration

Benchmarks are excluded from `pytest` default runs (`-m 'not slow'` in pyproject.toml).
Run them in a separate CI job after merging Phase 8:

```bash
ATELIER_LLM_BACKEND=openai uv run pytest tests/benchmarks/context_quality/ -v -m slow
```
