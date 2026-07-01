# Baseline: Claude Code 2.1.152 / Claude Opus 4.8 on Terminal-Bench 2.1

Reference numbers scraped from the public tbench.ai leaderboard, for comparing
Atelier's own Harbor runs (`../atelier/<run>/...`) against the official
Claude Code result on the same benchmark.

**Source (view live here):**
https://www.tbench.ai/leaderboard/terminal-bench/2.1/claude-code/2.1.152/claude-opus-4-8%40anthropic

Each task on that page links to a per-task detail view
(`.../claude-opus-4-8%40anthropic/<task-checksum>`) listing all 5 trials with
input/output/cache tokens, cost, and duration — that per-trial table is what
was scraped here.

## How this was collected

tbench.ai is a Next.js app that ships each page's data as a JSON blob
embedded in the server-rendered HTML (no public API). The data was pulled
straight from that HTML with `curl` — fetch the model's leaderboard page to
get the task → checksum map, then fetch each task's detail page and parse its
rendered results table. No browser/JS execution needed. Ad-hoc scripts used
for this are not checked in; re-run by re-scraping the URL above if the data
needs refreshing (e.g. after a new terminal-bench version or rep).

## Files

- **`tbench_opus48_claudecode_2.1.152_tasks.csv`** — one row per trial
  (89 tasks × 5 reps = 445 expected, 440 present; see Gaps below).
  Columns: `task, trial_name, result, input_tokens, output_tokens,
  cache_tokens, total_tokens, cost_usd, duration, duration_seconds`.

- **`tbench_opus48_claudecode_2.1.152_per_task.csv`** — one row per task,
  rolled up across its reps. Columns: `task, n_reps, n_pass, n_fail,
  n_no_data, pass_rate, avg_input_tokens, avg_output_tokens,
  avg_cache_tokens, avg_total_tokens, total_cost_usd, avg_cost_usd,
  total_duration_seconds, avg_duration_seconds`.

- **`summary.txt`** — single-run-level rollup: totals and per-trial /
  per-task(×5) averages for tokens and cost, total wall-clock duration,
  overall pass rate, and the costliest / lowest-pass-rate tasks. Generated
  from the per-trial CSV above.

- **`tbench_opus48_claudecode_2.1.152_aggregate.csv`** — grand totals, two
  rows for two different scopes (same columns: `scope, n_tasks,
  n_trials_or_tasks, n_pass, n_fail, n_no_data, pass_rate,
  total_input_tokens, total_output_tokens, total_cache_tokens,
  total_tokens, total_cost_usd, total_duration_seconds,
  total_duration_hours`):
  - `all_reps` — sum over every one of the 440 trials (all 5 reps of all 89
    tasks). This is "run the whole suite 5x": $288.15, 73.4h.
  - `one_run` — sum of each task's *per-task average* (from
    `per_task.csv`), i.e. the cost of a single pass through all 89 tasks
    (one rep each): $57.90, 14.8h. `n_pass`/`n_fail` here are expected
    values (sum of per-task pass rates), not integers, since the average
    blends reps that did and didn't pass.

## Known gaps (verified against tbench.ai itself, not scraping bugs)

- **Cache tokens are combined read+write.** tbench.ai only exposes a single
  `cache_tokens` figure per trial, in both its rendered table and its
  underlying data — there is no cache-write / cache-read split available
  from this source at any granularity.
- **`rstan-to-pystan`** has only 4 of 5 reps on tbench.ai — the 5th isn't in
  their table at all.
- **`compile-compcert__gFqkD3K`** ran (60m 36s, recorded as a fail) but
  tbench.ai shows `N/A` for its tokens/cost, left blank here to match.
- **`protein-assembly`** has zero per-trial data on tbench.ai (page shows
  "No trial data available"); all 5 reps failed with no telemetry captured.
  Represented as a single placeholder row with `result = no data available`.

## Cost comparison vs. Atelier's own run (`../atelier/2026-07-01__01-00-07/`)

**`atelier_vs_baseline_per_task.csv`** — per-task comparison against Atelier's
Harbor run, matched on the 82 tasks both sides have cost data for. Columns:
`task, baseline_resolved (x/5), atelier_resolved, baseline_avg_cost_corrected,
atelier_cost, save_pct, baseline_rep_costs_corrected` (JSON list of the 5
corrected per-rep costs).

**Why "corrected":** tbench.ai's displayed cost treats cache tokens as **$0**
(see Known gaps below) while Atelier's `pricing.yaml` correctly bills
cache reads ($0.50/M) and cache writes ($6.25–$10/M). To compare like for
like, baseline costs here are recomputed as
`(input − cache) × $5/M + output × $25/M + cache × blended_cache_rate`,
where the blended cache rate uses a **~5.1% write / 94.9% read** split — the
actual ratio measured from one real Atelier trial's raw Claude usage report
(`cache_creation_input_tokens` vs `cache_read_input_tokens` in
`agent/claude-run.json`). tbench.ai doesn't expose a per-trial read/write
split, so this ratio is an estimate applied uniformly, not a measured value
per baseline trial.

**Result:** matched on 82 tasks, Atelier totals **$128.03** vs. baseline's
corrected **$87.67** (**1.46x**). The overhead is not uniform:

| Baseline task cost | n tasks | avg baseline | avg atelier | avg delta |
|---|---|---|---|---|
| < $0.50 | 35 | $0.29 | $0.63 | +$0.34 (2.2x) |
| $0.50–$1.50 | 31 | $0.92 | $1.13 | +$0.21 (1.2x) |
| ≥ $1.50 | 16 | $3.05 | $4.45 | +$1.40 (1.5x) |

Cheap tasks take the worst relative hit (a handful show 400–800% overshoot,
e.g. `code-from-image`, `fix-code-vulnerability`) — consistent with a
fixed per-run overhead paid regardless of task size. Unlike the SWE-bench
comparison (see top-level README), that overhead does **not** fully wash out
on bigger tasks here — only the priciest tasks (baseline ≥ ~$2.40, e.g.
`train-fasttext`, `regex-chess`, `caffe-cifar-10`) consistently come out
cheaper on Atelier. 51/82 matched tasks cost more, 31/82 cost less. 5 tasks
(`gpt2-codegolf`, `hf-model-inference`, `kv-store-grpc`,
`mcmc-sampling-stan`, `pytorch-model-recovery`) have a pass/fail result but
no cost telemetry — the agent process crashed/timed out before Claude Code
wrote a final usage report, so the true Atelier total is higher than $128.03.

## Regenerating the rollups

Both derived files are computed purely from the per-trial CSV — if that CSV
is updated/replaced, regenerate the other two from it (group by `task`,
average/sum the numeric columns, skip blank cells).
