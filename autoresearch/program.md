# program.md — Atelier cost-efficiency loop

You are an autonomous engineer making **Atelier** cheaper **at the same model**.
Read this fully, then run the loop. Ported from karpathy/autoresearch: a fixed
eval scores each attempt; you KEEP improvements and `git reset` failures.

## Mission (hard target)

On SWE-bench (claude-opus-4-8, both arms), drive Atelier to **>=50% cheaper than
the vanilla baseline** while keeping **correctness same-or-better**. Time is
ignored. `eval.py` reports `savings_pct`, `correct`, and `target_met`.

## The one rule that defines this work

Savings MUST come from **token efficiency at claude-opus-4-8** — fewer/leaner
tokens, more prefix-cache reuse, fewer wasted turns. **Never** route the agent's
driver to a cheaper model (haiku/sonnet). That is the forbidden shortcut.

## Roles

- You (a Claude instance) propose ONE change per iteration and run the eval.
- `eval.py` is the scorer (frozen). The baseline is frozen
  (`baseline/swe30.json`) and only the **atelier arm** is ever re-run — the
  baseline is invariant to your edits.
- A human reviews every KEEP before it sticks.

## What you CAN edit (controlled search space — soft persona + hard tooling)

**Soft — persona (behavioral):**
- `integrations/agents/**` — per-mode persona / instructions.
- `integrations/shared/**` — shared persona fragments (coding-guidelines, discipline).
- `scripts/sync_agent_context.py` — the persona-sync generator. After ANY persona edit run
  `make sync-agent-context` (host files regenerate) and ensure `make check-agent-context` passes.

**Hard — tooling (deterministic): the FULL per-task token-cost pipeline at fixed model.**
Edit behavior where it lives. Grouped by lever (cost = cache_read = context × turns + output):
- *Context assembly*: `core/runtime/engine.py` (`get_context`), `core/capabilities/context_reuse/**`,
  `core/service/bootstrap_context.py`, `core/foundation/{renderer,retriever}.py`.
- *Recall / memory / embeddings*: `core/capabilities/archival_recall/**`, `core/capabilities/memory/**`,
  `core/capabilities/semantic_file_memory/**`, `infra/embeddings/**` (shapes what recall injects + prewarm).
- *Tool-result size / compaction*: `core/capabilities/tool_supervision/**` (shell/bash, search/read,
  post-edit hooks, compact_output, spill), `core/capabilities/source_projection/**`,
  `infra/runtime/context_compressor.py`, and result rendering in `mcp_server.py`.
- *Code tools*: `core/capabilities/code_context/**` (read/grep/search/edit/codemod).
- *Anti-churn / turns*: `core/capabilities/loop_detection/**`, the tool cache in `tool_supervision/**`,
  `core/capabilities/quality_router/**` (NON-model parts only).
- *Prompt caching*: `core/capabilities/prefix_cache/**`, `core/capabilities/prompt_compilation/**`.
- *Dedup / compression*: `core/capabilities/context_dedup.py`, `core/capabilities/context_compression/**`.
- *Verify-before-done*: `core/capabilities/verification/**`.
- *Adapter*: `gateway/adapters/mcp_server.py` (wiring + result rendering).

**Config — env knobs (the MOST controlled: pure config, deterministic, reversible):**
- `autoresearch/knobs.env` — set `ATELIER_*` overrides; `eval.py` injects them into the atelier
  arm via the `.env` cascade (overrides incontainer defaults). Prefer a knob over a code edit.
  Cost knobs: `ATELIER_SHELL_MAX_OUTPUT_BYTES` (def 4MiB), `ATELIER_READ_MAX_BYTES` (8MiB),
  `ATELIER_OUTLINE_THRESHOLD`, `ATELIER_SEARCH_BREAKER_THRESHOLD` (def 6),
  `ATELIER_SEARCH_REFORMULATION_THRESHOLD` (2), `ATELIER_RECALL_CANDIDATE_LIMIT` (2000),
  `ATELIER_CTX_NUDGE_TOKENS`, `ATELIER_EXPLORE_SKELETON`. Already tuned (leave unless re-testing):
  `ATELIER_HIDE_TOOLS`, `ATELIER_EDIT_VERIFY=1`, `ATELIER_CODE_EMBEDDER=local`.

- `tests/**` — add/strengthen only.

## What you CANNOT edit / do

- **Model-tier selection** — `core/capabilities/model_routing/**`, `cross_vendor_routing/**`, and the
  model-tier parts of `optimization/**` / `lesson_promotion/cost_cap.py` — forbidden (fixed-model rule).
- **Out-of-band** (don't change tokens-to-model): `core/service/telemetry/**`, `licensing/**`,
  `security/**`, storage backends (`infra/storage/**`), `audit_export`/`reporting`/`team`,
  `infra/code_intel/**` index internals. (`optimization/**` is mostly measurement — not a token lever here.)
- `autoresearch/eval.py`, `program.md`, `plot.py`, `freeze_baseline.py` — the harness.
- `autoresearch/baseline/*.json`, `autoresearch/tasks/*.txt` — frozen refs & task sets.
- `benchmarks/**` — the scorer (no gaming grading or cost accounting).
- `pyproject.toml` deps — no new deps without approval.
- **Change/downgrade the model** — forbidden (see the one rule).
- `landing/` submodule.

## Setup (once)

1. Branch: `git checkout -b autoresearch/<tag>`.
2. Confirm the baseline is frozen: `autoresearch/baseline/swe30.json` (model claude-opus-4-8).
3. Sanity dry-run (no spend): `uv run python autoresearch/eval.py --objective swe --dry-run`.

## The loop (repeat; never ask permission to iterate)

1. Pick ONE token-efficiency idea from the backlog.
2. Edit the source — the smallest change that tests it.
3. Make the atelier arm use your edit (if you touched `integrations/claude/plugin`
   run `bash scripts/install_claude.sh`; `src/atelier` is used live via the
   editable install). When unsure, do a 1-task sanity run first.
4. Commit: `git add -A && git commit -m "<idea>"`.
5. Evaluate on the iterate set (atelier arm only, opus-4-8):
   `uv run python autoresearch/eval.py --objective swe --tasks autoresearch/tasks/iterate.txt --reps 1 --json autoresearch/last.json --log autoresearch/results.tsv --desc "<idea>"`
6. Read the block: `savings_pct`, `atel_resolved` vs `base_resolved`, `reliability_regressions`.
7. Decide (await human approval on KEEP):
   - KEEP if `correct: True` (resolved >= baseline) AND `savings_pct` improved AND no new `reliability_regressions`.
   - REVERT otherwise: `git reset --hard HEAD~1`.
8. `uv run python autoresearch/plot.py`. Repeat.

## Validation (avoid overfitting)

- Iterate cheap on `tasks/iterate.txt` (atelier-only, reps=1).
- Gate on a held-out split: `uv run python autoresearch/make_holdout.py` → freeze
  its baseline once → eval on `tasks/holdout.txt`. It must improve too.
- Final: full swe30 at reps=3 before declaring the target met
  (`--tasks benchmarks/codebench/data/verified.txt --reps 3`).

## Decision discipline

- The correctness floor is absolute: never trade a resolved task for savings.
- A change that cuts tokens while holding correctness is a KEEP, even if small.
- Prefer changes that generalize (key off task signals, not task ids).

## Experiment backlog — evidence-backed, in-scope (soft persona | hard tooling)

Cost = cache_read (context × turns) + output. Two controlled experiment types:

**HARD tooling (`mcp_server.py`) — deterministic, low correctness risk:**
- Cap/trim large `shell` tool-results that persist in the transcript. Evidence: shell
  output = 94.6% of sklearn-25102's transcript tool-bytes; the largest blocks are
  multi-thousand-char `git log` dumps. Pre-check: capping @~2k chars/call est. saves
  ~$4/run of cache_read (concentrated in seaborn / sklearn / django).
- Same idea for verbose `read`/`grep`; "summarize-on-carry" — full output in the
  producing turn, a short summary in history so later turns re-read less.
- (Correctness, if the floor needs protecting) the verify-before-done gate lives here too.

**SOFT persona (`integrations/`) — behavioral; run `make sync-agent-context` after:**
- Discourage broad git-history archaeology (`git log --all` spelunking — sklearn ran 76
  unique git-log commands). Prefer one targeted lookup.
- Bias toward decisiveness / fewer verification turns. Turns multiply ALL cost
  (cache_read = context × turns), so this is the highest-headroom lever.
- Right-size exploration to task size (small tasks regressed: django-12155, flask-5014).

Measure each; keep only on savings with correctness held.

## Safety

- Branch `autoresearch/<tag>` only, never main. `git reset --hard HEAD~1` undoes
  only the latest experiment commit; never reset past the baseline.
