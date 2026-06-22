# autoresearch — cost-efficiency loop for Atelier

A self-contained harness that lets an AI agent iteratively make Atelier cheaper:
**propose a change → run a fixed eval → keep it if it improves, revert if not.**
Every attempt is logged to `results.tsv` and charted to `progress.png`.

Ported from [karpathy/autoresearch](https://github.com/karpathy/autoresearch) and
[jyotilakra92/auto-improving-kernel](https://github.com/jyotilakra92/auto-improving-kernel):
a fixed eval + an editable artifact + a git keep/revert loop. Here the artifact
is the Atelier source and the metric is its **SWE-bench $/run vs vanilla**.

## Target

**>=50% cheaper** than the vanilla baseline on SWE-bench, **correctness
same-or-better**, **at the same model (claude-opus-4-8)**. Time is ignored.
Savings must come from token efficiency — never from routing to a cheaper model.

## Search space (controlled)

The loop edits two surfaces. **Soft persona**: `integrations/agents/**`,
`integrations/shared/**` (synced via `scripts/sync_agent_context.py`). **Hard tooling** — the
full per-task token-cost pipeline at fixed model: context assembly (`core/runtime/engine.py`,
`context_reuse`, `bootstrap_context`), recall/embeddings (`archival_recall`, `memory`,
`semantic_file_memory`, `infra/embeddings`), tool-result compaction (`tool_supervision`,
`source_projection`, `context_compressor`), code tools (`code_context`), anti-churn
(`loop_detection`, `quality_router` non-model), caching (`prefix_cache`, `prompt_compilation`),
dedup/compression (`context_dedup`, `context_compression`), verify (`verification`), and
`gateway/adapters/mcp_server.py`. Off-limits: model-tier routing (fixed-model rule) and
out-of-band subsystems (telemetry, licensing, security, storage backends, code-intel indexing).
“Controlled” = each experiment runs one-at-a-time, evidence-first, measured, gated — not a tiny
file list. See `program.md` for the full contract.

## Files

| file | role |
| --- | --- |
| `program.md` | the agent's loop instructions (the "skill"). Point Claude at this. |
| `eval.py` | **fixed** scorer. Runs the atelier arm, compares to the frozen baseline, prints a grep-friendly block. |
| `freeze_baseline.py` | freeze the vanilla baseline once from a prior graded run (it's invariant to Atelier edits). |
| `make_holdout.py` | sample a held-out split (disjoint from swe30) to guard against overfitting. |
| `plot.py` | renders `results.tsv` → `progress.png`. |
| `baseline/swe30.json` | the frozen baseline (per-task rep-normalized cost + solve rate). Off-limits to the loop. |
| `tasks/iterate.txt` | representative subset for cheap iteration. |
| `results.tsv` | experiment log (git-ignored). |

## Why baseline-frozen + atelier-only

The baseline (vanilla Claude Code) depends only on (task, model) — it does not
change when you edit Atelier. So we measure it **once** and only ever re-run the
**atelier arm**, roughly halving the spend per iteration. Re-freeze only if the
model changes.

## Quick start

```bash
# 1. Freeze the baseline from your last graded swe30 run (once):
uv run python autoresearch/freeze_baseline.py detect
uv run python autoresearch/freeze_baseline.py freeze <run_dir> --out autoresearch/baseline/swe30.json

# 2. Sanity-check the plan (no spend):
uv run python autoresearch/eval.py --objective swe --dry-run

# 3. Hand program.md to an agent, or run one eval manually:
uv run python autoresearch/eval.py --objective swe \
    --tasks autoresearch/tasks/iterate.txt --reps 1 \
    --json autoresearch/last.json --log autoresearch/results.tsv --desc baseline-check

# 4. Chart progress:
uv run python autoresearch/plot.py
```

The metric block (between `---` fences) is the source of truth:

```
---
objective: swe
correct: True            # resolved >= baseline (correctness floor)
score: 51.3              # = savings_pct
savings_pct: 51.3
atel_resolved: 25.7
base_resolved: 25.0
reliability_regressions: 0
target_met: True         # >=50% cheaper AND correctness held
---
```

## Other objectives

`--objective health` (free: tests+mypy+ruff) and `--objective mini` (the fast
cost/quality proxy) remain available for quick local checks.

## Safety

- The agent runs on a dedicated `autoresearch/<tag>` branch, never `main`.
- The harness, frozen baseline, task sets, and `benchmarks/**` are off-limits to
  the loop — it can't game its own scorer.
- Model downgrade is forbidden; new dependencies need approval.
