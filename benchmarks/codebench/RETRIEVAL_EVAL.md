# Retrieval eval — explore/search MRR + latency

Offline eval of Atelier's code retrieval, scored by **rank-of-gold-file** over
mined SWE-bench `(query, gold-file)` pairs across the diverse-5 repos
(django, astropy, xarray, pytest, scikit-learn). Reports **MRR / hit@1 / hit@3**
and **per-query latency**. Use it to compare retrieval channels and to guard
against regressions when changing `_search_symbols_local` / fusion / ranking.

## Channels

| # | Channel | Harness | What it exercises |
|---|---------|---------|-------------------|
| 1 | **Lexical** | `fitness_explore_mrr.py` | `tool_explore` symbol FTS/trigram + ranking (no zoekt binaries on PATH) |
| 2 | **+ Zoekt fusion** | `fitness_explore_mrr.py` (zoekt installed) | adds zoekt trigram-anchor files to the fusion (auto-on when binaries resolve) |
| 3 | **BGE semantic** | `eval_semantic_mrr.py` | standalone embedding retrieval (BGE-Code-v1) over the pre-built corpus |
| 4 | **CMM (codebase-memory-mcp)** | `eval_cmm_mrr.py` | external arm: DeusData's knowledge-graph MCP server (`search_graph` BM25 + bundled nomic-embed-code) over an independently-built index |

Channel 4 is an **external retrieval provider** (not Atelier): a fair, independent
baseline that builds its own index, so unlike channels 1–3 it does not share the
gold's index-derivation. Run it via `atelier eval retrieval --channel cmm` or the
standalone `eval_cmm_mrr.py` (see the CMM section below).

Channels 1–2 are the SHIPPED `tool_explore` path. Channel 3 is a standalone probe
(semantic is not yet fused into explore) answering "does the embedder help these
queries?" before investing in fusion.

## Latest results (single-worker, n=566 pairs)

| Channel | MRR | hit@1 | hit@3 | latency / query |
|---------|-----|-------|-------|-----------------|
| baseline (pre-work) | 0.220 | — | — | — |
| 1. Lexical (IDF + df-budget) | 0.394 | 0.315 | 0.429 | 247 ms explore · 48 ms search-core |
| 2. + Zoekt fusion | **0.478** | 0.392 | 0.505 | 632 ms explore (+385 ms zoekt subprocess) |
| 3. BGE semantic (standalone) | 0.446¹ | 0.327 | 0.498 | 16 ms embed+cosine (GPU) |

¹ 0.456 excluding scikit-learn: its gold files (`sklearn/decomposition/dict_learning.py`,
`examples/…`) are absent from the pre-built BGE corpus (coverage gap, n=12), so semantic
cannot be scored there.

## Provisioning (one-time)

- **Pairs + per-repo index DBs**: `scripts/_provision_repos.py` provisions each repo to a
  prebuilt read-only `(ws, db)`, writes the raw query universe to `bench_pairs_multi.json`,
  then derives the canonical **definition gold** `bench_pairs_def_gold.json` (via
  `build_definition_gold.py`) — the single gold every eval reads. Override the path with
  `EVAL_PAIRS` / `FITNESS_PAIRS`.
- **Zoekt (channel 2)**: install the binaries on `PATH` and build per-repo indexes:

  ```bash
  GOBIN=$HOME/go/bin go install github.com/sourcegraph/zoekt/cmd/{zoekt,zoekt-index,zoekt-git-index,zoekt-webserver}@latest
  # build an index per repo workspace (ws): ZoektSupervisor(ws).server.ensure_started_and_build()
  ```

- **BGE corpus (channel 3)**: pre-built vectors live in
  `benchmarks/embedding/data/multi_repo/emb_bge_<repo>.npy` + `corpus_<repo>.jsonl`
  (built by `benchmarks/embedding/bench_multi_repo.py`). Needs `sentence-transformers`
  - `torch` (see `benchmarks/embedding/requirements_hf.txt`) — NOT the project venv.

## Running

```bash
# Channel 1 (lexical) — single-worker is required for trustworthy latency numbers.
FITNESS_WORKERS=1 uv run python benchmarks/codebench/fitness_explore_mrr.py

# Channel 2 (+ zoekt) — same command with zoekt on PATH; lower the LOC gate so
# sub-500k-LOC repos route to zoekt.
PATH="$HOME/go/bin:$PATH" ATELIER_ZOEKT_MODE=installed ATELIER_ZOEKT_LOC_THRESHOLD=1 \
  FITNESS_WORKERS=1 uv run python benchmarks/codebench/fitness_explore_mrr.py

# Channel 3 (semantic) — run with the benchmark env that has sentence-transformers.
python3 benchmarks/codebench/eval_semantic_mrr.py
```

Each prints one JSON line: `{mrr, hit1, hit3, n, latency_ms:{mean,p50,p95,max,over_100ms}, by_repo}`.
`FITNESS_SAMPLE=N` caps unique queries/repo for a fast signal; `FITNESS_REPO=django`
filters to one repo.

## Notes / caveats

- **Latency** is per-query wall-clock; only trustworthy with `FITNESS_WORKERS=1`
  (parallel workers contend on CPU and inflate each call).
- **Zoekt latency** is dominated by a per-query subprocess; a persistent
  `zoekt-webserver` would cut it. The 500k-LOC default gate keeps normal repos
  off zoekt by default.
- The harness stubs the retrieval cache (force-miss) so each run measures its own
  ranking, and the per-repo index DBs stay effectively read-only.

---

## Symbol-level semantic fusion + per-repo finetuning (2026-06-28)

Goal: wire a **lexical + zoekt + semantic** channel, build `symbol_vectors` for
the bench repos, measure the **semantic lift / ceiling**, then finetune the
embedder per-repo (atelier first). All semantic work uses **BGE-Code-v1**
(`bge:BAAI/bge-code-v1`, 1536-d) on a single RTX 4090.

### What was built

- **`symbol_vectors` for all 13 bench repos** (BGE-Code-v1). 7 were already
  stamped; the other 6 (matplotlib, seaborn, flask, requests, pylint, sphinx)
  were embedded via `experiments/retrieval_symbol_vote/build_bge_vectors.py`
  (one shared GPU model, repos sequential — GPU is the bottleneck, so parallel
  processes only contend / OOM). Vectors land in the engine's attached
  `vectors` db (the shared `/tmp/vectors.sqlite`, keyed by `repo_id`) for repos
  embedded through the engine path, and in the main db for the originally
  provisioned ones.
- **`eval_fused_mrr.py`** — channel 4. Single process (one BGE model, queries
  batched per repo): for each pair it scores three file rankings against the
  same gold, plus an oracle:
  - `lexzoekt` = `tool_explore` (the shipped lexical+zoekt fusion, **unchanged**);
  - `semantic` = cosine over `symbol_vectors`, projected symbol→file;
  - `fused` = file-level weighted RRF of the two (engine defaults k=60, w=1/1);
  - `oracle` = best-of(lex, sem) per query — the ceiling a perfect fuser could reach.

### Results (full set, n=2306)

| arm | MRR | hit@1 | hit@3 |
|-----|-----|-------|-------|
| lexical+zoekt | **0.7577** | 0.679 | 0.834 |
| semantic (BGE base, symbol-level) | 0.6322 | — | — |
| fused (equal-weight RRF) | 0.7202 | — | — |
| **oracle** (best-of per query) | **0.7951** | — | — |

- `lexzoekt`=0.758 reproduces the shipped `fitness_explore_mrr.py` baseline (~0.76)
  → the harness is apples-to-apples.
- **Naive equal-weight fusion REGRESSES (-0.0375).** On this grep/symbol-style
  benchmark, lexical+zoekt is near-optimal and base-BGE semantic adds noise to the
  strong lexical top-ranks.
- **Oracle ceiling = +0.0374** (0.758→0.795); 18 queries where lexical misses
  top-10 but semantic hits top-3. Real but modest complementary signal — capturing
  it needs a learned fuser / weighting, not equal-weight RRF.

### Per-repo finetuning (atelier)

Train on **synthetic** grep queries mined from atelier source (`synthetic_pair_miner`,
5787 pairs, query-distinct from the bench), evaluate on the **real** atelier bench
queries. BGE-Code-v1 finetuned with `MultipleNegativesRankingLoss`, bf16 + gradient
checkpointing + max_seq=512 (full fp16 finetune OOMs 24 GB), 2 epochs.

| eval | base | finetuned | Δ |
|------|------|-----------|---|
| file-level MRR (1373-file corpus, n=335) | 0.0643 | 0.0713 | +0.007 |
| symbol-level semantic MRR (full atelier, n=335) | 0.5772 | 0.5673 | **−0.010** |

**Finetuning on synthetic-grep queries gives ≈0 lift on the (grep-style) eval
queries** — both granularities agree. The bench queries are lexical by nature, so
there is little semantic signal for an embedder (base or finetuned) to add.

### Methodology caveats discovered (don't repeat)

- **Sample bias:** `--sample N` takes `sorted(queries)[:N]` — an *easier*, biased
  subset (atelier sample-150 lex=0.81 vs full 0.67). Headline numbers use the full set.
- **Live-repo stale vectors:** atelier is the live repo; editing files shifts
  `symbol_id`s, so vectors built earlier mis-align with the current `symbols`
  table and the semantic arm is *understated* (atelier full-run sem read 0.202
  until vectors were rebuilt from the current symbols → 0.577). Static `/tmp`
  repos are unaffected.
- **Build hazards:** fork+CUDA OOM (don't embed in a fork pool — one shared model,
  sequential); the shared `/tmp/vectors.sqlite` attach locks across sequential
  engines (build through `engine._reuse_connection()`, or one process per repo);
  `uv run` re-syncs the project env to base and strips `uv pip install`-ed torch —
  run GPU work from a dedicated `.venv-embed` (torch + sentence-transformers +
  accelerate + datasets + editable atelier).

### Running

```bash
# Build BGE symbol_vectors for the bench repos (idempotent; skips bge-stamped repos)
ATELIER_CODE_EMBEDDER=bge .venv-embed/bin/python \
  experiments/retrieval_symbol_vote/build_bge_vectors.py [--only sphinx,flask] [--model <path>]

# Fused MRR: lexical+zoekt vs semantic vs fused vs oracle (one query set, all arms)
.venv-embed/bin/python benchmarks/codebench/eval_fused_mrr.py \
  [--repo atelier] [--sample N] [--model <finetuned-dir>] [--no-explore] \
  [--rrf-k 60 --w-lex 1.0 --w-sem 1.0]
```

### Productised command

`atelier code train --name=embedding` (in `gateway/cli/commands/code.py`,
`[EXPERIMENTAL]`, needs `pip install -e '.[semantic]'`) wraps the pipeline
mine → prepare → finetune → eval for any repo. `--dry-run` prints the plan.

### Conclusion / next steps

The semantic ceiling on *this* benchmark is low because the queries are
grep/symbol-style — exactly where lexical+zoekt wins. **Do not fuse semantic into
the shipped explore path yet** (it regresses under equal-weight RRF). To realise
the embedder's value: (1) evaluate and train on **NL / prose** queries (real agent
`explore` queries), not grep patterns; (2) capture the oracle ceiling with a
**learned fuser / weighting** rather than equal-weight RRF. The full pipeline
(symbol-vector build, GPU finetune, fused-MRR harness with oracle, CLI command) is
in place and validated to do exactly that once NL-query data is available.

---

## DECISION (2026-06-29): do NOT wire semantic into explore yet

Gated full run, n=1562 main-DB repos (equal weight unless noted):

| config | MRR | lift vs lexical |
|---|---|---|
| lexical | 0.6712 | — |
| semantic alone | 0.5841 | −0.087 |
| fused (equal weight, all queries) | 0.6526 | −0.019 |
| fused, best weight (w_sem=0.75) | 0.6696 | −0.002 |
| **shape-gate: fuse alternations only** | **0.6750** | **+0.0038** |
| oracle (best-of per query) | 0.7336 | +0.062 |

Fusion lift **by query shape** (the crux):

| bucket | n (share) | lexical | semantic | fused |
|---|---|---|---|---|
| alternation | 359 (23%) | 0.453 | 0.428 | **0.470 (+0.017)** |
| multiword | 274 (18%) | 0.533 | 0.417 | 0.464 (−0.069) |
| single-token | 929 (60%) | 0.796 | 0.694 | 0.779 (−0.017) |

Fusion helps **only on alternations** (where lexical FTS structurally choked) and
hurts the other 78% of queries. Even a perfectly targeted static shape-gate yields
**+0.004 MRR** — semantic's realizable lift here is ~0. The +0.062 oracle ceiling is
NOT reachable with a static gate (most oracle wins are queries where you can't tell
a priori which channel is right); it needs a learned per-query fuser reading both
rankings' confidence, and is still modest.

Other measured ≈0 levers this session: per-repo embedder finetune (file-level +0.007,
symbol-level −0.010); richer embedding text name+sig+doc+1200ch body (−0.014, dilutes
the name signal). The one real win is **lexical**: the exact-name channels in
`_search_symbols_local` only matched the *whole* query string, so an `a|b|c`
alternation matched no symbol and never got the exact-definition pin — fixed by
splitting on `|` and matching each identifier via `symbol_name IN (...)`. That
removes semantic's one niche for free (no GPU model).

**Conclusion:** keep `tool_explore` lexical+zoekt. Revisit semantic only with
**NL/intent eval+train queries** — the only regime where semantic ranked #1.
Fusion-weight tuning, richer embeddings, and finetuning are all ≈0 on this
grep-shaped benchmark.

---

## The gold was flawed for retrieval — use the DEFINITION gold

The shipped `bench_pairs_multi.json` gold is the file the SWE-task PR **edited**
(edit-localization). For a *search* eval it is mislabeled. Measured on atelier
(n=335): **45% of golds are test files**, and by whether the gold defines a symbol
the query names:

| category | share | lexical MRR |
|---|---|---|
| gold defines a query symbol (fair) | 48% | **0.945** |
| query symbol defined in a NON-gold file | 40% | 0.363 |
| query names no known symbol | 12% | 0.566 |

**Of the misses, 85% are "gold-elsewhere" and 0% are "gold-defines"** — the
retriever never misses when the gold is the right answer; it "misses" because the
gold is the edited test, not where the query's symbols live (e.g. query
`apply_fuzzy_replace|resolve_symbol_edit` → defined in `symbol_edit.py`/`fuzzy_match.py`,
but gold = `tests/.../test_rich_edit_symbol.py`). So ~0.67 was a **labeling
ceiling, not a retrieval ceiling**.

### Fix: `build_definition_gold.py`

Regenerates the gold as the file(s) that **define** the specific symbols each query
names (a bare symbol name defined in ≤`--max-def` files, length ≥`--min-len`, not a
common token), auto-derived from each repo's symbol index. Three gates keep only the
*reliably-labelable* subset: (1) queries naming no specific symbol are dropped (they
need an NL eval); (2) the **purity gate** drops descriptive queries (see below); (3)
multi-symbol queries scattered across files (no file defines ≥2 of them) are dropped
as ambiguous.

```bash
uv run --no-sync python benchmarks/codebench/build_definition_gold.py \
    --out benchmarks/codebench/data/bench_pairs_def_gold.json
# 1357/1924 queries scorable (71%), avg ~1.3 gold files/query, 10 repos (--min-purity 0.5)
```

#### The purity gate — why atelier was the outlier

With only gates (1)+(3), atelier read **0.756** while every other repo sat at
0.93–1.0. The cause was *gold-derivation noise on descriptive queries*, not
retrieval: atelier is the most polyglot/descriptive-query-heavy repo, and a
lowercase English phrase like `no install-time indexers detected SCIP message`
has a couple of words that *coincidentally* name a bare symbol in an unrelated
file, so the auto-gold points at e.g. `api.ts`. The retriever returns sensible
files; the *label* is wrong (atelier `absent(>30)` rate was 15%, vs 0%
gold-not-in-index — the gold was always indexed, just wrong).

The gate: `purity = n_specific / n_word_tokens` — the fraction of a query's
word-tokens that are real symbols. A bare symbol or a clean alternation of
symbols has purity ≈1.0; a descriptive sentence has a few coincidental hits among
many ordinary words, so purity is low. `--min-purity 0.5` (default) drops the
descriptive tail. Effect on atelier:

| min-purity | atelier n | atelier MRR | hit@1 | absent(>30) |
|---|---|---|---|---|
| 0.0 (off) | 209 | 0.756 | 73% | **15%** |
| **0.5** | 163 | **0.873** | 85% | 6% |
| 0.67 | 133 | 0.941 | 93% | 3% |

0.5 is the cut: it removes label noise (the worst surviving misses become genuine
rank-11–14 ranking problems, not spurious golds), while 0.67 over-prunes (the
alternation bucket collapses to n=12) and its residual misses are regex-pattern
queries (`re\.(sub|compile)`). The gate is a pure query filter — it changes no
retrieval behavior, so repos already at 0.93–1.0 only hold or rise.

Use it via the existing harness knobs (it keeps the `{pairs, true_map, repos}`
shape, one stable id per query):
```bash
./.venv-embed/bin/python benchmarks/codebench/eval_fused_mrr.py \
    --pairs benchmarks/codebench/data/bench_pairs_def_gold.json
FITNESS_PAIRS=benchmarks/codebench/data/bench_pairs_def_gold.json \
    FITNESS_WORKERS=1 uv run python benchmarks/codebench/fitness_explore_mrr.py --full
```

### Validation (definition gold, 6 vector repos, n=1063)

| arm | SWE-edit gold | definition gold |
|---|---|---|
| lexical | ~0.67–0.76 | **0.9082** |
| semantic | — | 0.7520 |
| fused (w=1) | — | 0.8684 (−0.040) |
| oracle | — | 0.9214 (+0.013) |

By shape: single-token lexical **0.998** (solved), alternation 0.795, multiword 0.743.

### Cross-repo lexical on the purity-gated gold (n=1357, --min-purity 0.5)

| repo | n | MRR@10 | repo | n | MRR@10 |
|---|---|---|---|---|---|
| matplotlib | 266 | 0.996 | astropy | 137 | 0.985 |
| xarray | 213 | 1.000 | django | 125 | 0.957 |
| pytest | 195 | 0.997 | seaborn | 87 | 0.990 |
| pylint | 143 | 0.995 | **atelier** | **163** | **0.873** |
| | | | **OVERALL** | **1357** | **0.977** |

The purity gate moved atelier **0.725 → 0.756 (consensus rule) → 0.873 (purity
gate)** — no longer a dramatic outlier (in band with django 0.957). Its residual
gap is real rank-11–14 alternation misses, not label noise.

Fixing the gold lifts measured lexical retrieval **0.67 → 0.91 (+0.24)** — the
retriever was always strong; the benchmark measured the wrong task. It also
**confirms the semantic verdict on a fair gold**: semantic 0.75 < lexical 0.91,
fusion regresses on every bucket, oracle ceiling +0.013. The grep-shaped query
distribution, not the gold, is why semantic doesn't help. **Adopt the definition
gold as the standard retrieval eval; keep the SWE-edit gold for edit-localization.**

---

## Channel 4 — codebase-memory-mcp (CMM) external arm + the Linux-kernel repo (2026-06-29)

Two additions: (a) a new **external retrieval provider** arm for DeusData's
[`codebase-memory-mcp`](https://deusdata.github.io/codebase-memory-mcp/), and
(b) the **Linux kernel** (core subsystems) added to the golden set + benchmark so
every arm can be evaluated on a genuinely large, C codebase.

### The CMM arm — `eval_cmm_mrr.py`

`codebase-memory-mcp` is a single static Go binary that indexes a repo into a
persistent knowledge graph (BM25 full-text + bundled `nomic-embed-code` semantic
edges, 158 languages, all local — no network, no API key). It exposes 14 MCP
tools; the arm uses two, mapped to the two golds exactly as the other external
arms (ctags/serena/jcodemunch) split symbol vs content:

| gold | CMM tool | result file-path key |
|---|---|---|
| definition | `search_graph` (graph BM25; handles `a\|b\|c` alternations natively) | `file_path` |
| content | `search_code` (grep + graph enrichment) | `file` |

The binary is driven in one-shot `cli <tool> '<json>'` mode (no MCP stdio
handshake needed — the same `graph.db` is read each call). Methodology is
identical to `eval_cg_mrr.py`/`fitness_explore_mrr.py`: same `(query, tid,
prefix)` pairs, same `FITNESS_PAIRS`/`FITNESS_SAMPLE`/`FITNESS_REPO` knobs, one
query per pair, rank-of-gold-file (endswith, top-10), one JSON line out. Each
repo is indexed once (idempotent). All CMM state lives under an isolated `$HOME`
(`CMM_HOME`, default `/tmp/cmm-bench`) so a run never touches a user's cache; the
pinned `v0.8.1` Linux binary is fetched on first use (or point `CMM_BIN` at it).

This is the **only arm that builds its own index** — channels 1–3 read Atelier's
symbol index, which is also what the definition gold is derived from, so CMM is
the fair external apples-to-apples baseline.

```bash
# via the CLI (downloads the pinned binary on first use)
atelier eval retrieval --channel cmm --full

# standalone (point CMM_BIN at the binary; def + content golds)
CMM_BIN=/path/to/codebase-memory-mcp \
  FITNESS_PAIRS=benchmarks/codebench/data/bench_pairs_def_gold.json,benchmarks/codebench/data/bench_pairs_content_gold.json \
  FITNESS_REPO=pydata__xarray \
  python benchmarks/codebench/eval_cmm_mrr.py
```

### Results — diverse-5 definition gold (single-worker, n=762)

| arm | MRR | hit@1 | hit@3 | latency / query |
|---|---|---|---|---|
| lexical (`tool_explore`) | **0.9739** | 0.9659 | 0.9803 | 28 ms |
| lexical + zoekt | 0.9701 | 0.9593 | 0.9803 | 36 ms |
| **CMM (`search_graph`)** | 0.8353 | 0.7966 | 0.8780 | ~40 ms (CLI subprocess) |

Per-repo CMM definition MRR: xarray 0.946, pytest 0.937, astropy 0.812, sklearn
0.713, **django 0.619** (django is the hardest — 55k symbols; CMM's BM25 graph
ranks the right file lower on its many name collisions). CMM **content** gold
(`search_code`) is stronger and closer to parity: astropy 0.918, xarray 0.963,
pytest 0.934, sklearn 0.85, django 0.395 → ~0.85 weighted.

Takeaway: CMM is a solid, fully-local external retriever (0.84 def MRR with **zero**
shared index with the gold), but Atelier's lexical `tool_explore` leads by
**+0.14 MRR** on this symbol-definition benchmark.

### The Linux kernel repo

Provisioned by `scripts/_provision_linux_kernel.py`. The full kernel (~64k C
files, ~30M LOC, mostly hardware-specific `drivers/`+`arch/`) is intractable and
unrepresentative to provision whole, so we **scope to the core subsystems**:

    kernel/ mm/ fs/ block/ ipc/ lib/ security/ crypto/ init/ virt/ include/

= ~11k C files / ~4.5M LOC — bigger than any diverse-5 repo (a real scale test)
yet tractable: Atelier indexes it in ~4 min (**1.24M symbols**), CMM in **25 s**
(690k nodes). `drivers/`, `arch/`, `net/`, `sound/` are deliberately excluded
(repetitive, hardware/arch-specific long tail).

The kernel has no SWE-bench grep dumps, so the gold is mined **from the symbol
index itself** — bare specific symbols + clean alternations of co-located symbols
— then run through the **same** `build_definition_gold.py` gates (purity/scatter/
`max_def`) as the diverse-5. Deterministic (seeded). Result: **591 scorable
pairs** (98% of 600 mined; 393 single-token + 198 alternation), avg 1.2 gold
files/query. Merged into the shared `bench_pairs_def_gold.json` (1561 → 2152
pairs), so every arm scores the kernel automatically.

```bash
uv run --no-sync python scripts/_provision_linux_kernel.py --prepare   # clone+scope+index
uv run --no-sync python scripts/_provision_linux_kernel.py --mine       # mine queries -> def gold
uv run --no-sync python scripts/_provision_linux_kernel.py --merge      # append into shared gold
```

### Results — Linux-kernel definition gold (single-worker, n=591)

| arm | MRR | hit@1 | hit@3 | latency / query |
|---|---|---|---|---|
| lexical (`tool_explore`) | **1.000** | 1.000 | 1.000 | 95 ms (p50 34 ms) |
| lexical + zoekt | 1.000 | 1.000 | 1.000 | 91 ms (p50 31 ms) |
| **CMM (`search_graph`)** | 0.7576 | 0.7208 | 0.7902 | 203 ms |

**Caveat (important):** lexical = 1.000 reflects a *home advantage* — the kernel
gold is derived from Atelier's own symbol index, so the lexical retriever (which
reads that same index) is structurally guaranteed to find the definition file.
The meaningful number here is **CMM at 0.758** — an *independent* retriever scored
on this gold — which shows CMM finds the right kernel definition file ~3/4 of the
time, at higher latency (the 690k-node graph). For an unbiased lexical-vs-CMM
comparison use the diverse-5 table above (whose gold matches lexical's index but
the gap is established and modest, +0.14); the kernel arm's value is scale
(does each arm hold up at 4.5M LOC) and the external CMM signal, not the saturated
lexical score.

### What is wired

- `benchmarks/codebench/eval_cmm_mrr.py` — the CMM arm.
- `scripts/_provision_linux_kernel.py` — kernel scope + index + gold mining + merge.
- `benchmarks/codebench/data/bench_pairs_linux_def_gold.json` — kernel-only def gold.
- `bench_pairs_def_gold.json` now carries `torvalds__linux` (591 pairs).
- `atelier eval retrieval --channel cmm` (CLI wiring in `gateway/cli/commands/eval.py`).
