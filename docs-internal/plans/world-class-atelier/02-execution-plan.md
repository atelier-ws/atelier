# World-Class Atelier — Subagent Execution Plan

> Created 2026-05-29. Executes [`01-second-audit.md`](01-second-audit.md).
> Orchestrated by the **main thread** (me); work delegated to **subagents**.
> Nothing is "done" until its **proof gate** shows a recorded number.

## 0. Roles & rules of engagement

**Orchestrator (main thread)** — owns: wave sequencing, worktree creation/merge,
proof gates (runs benchmarks + `make lint typecheck test`), and the final
result tables. Does **not** write feature code itself; delegates to `atelier:code`.

**Subagent types used** (from the available set):

| Agent | Use for | Edits files? |
|---|---|---|
| `atelier:research` | external facts: exact embed/rerank model + dims + license + Ollama availability | no |
| `atelier:explore` | internal blast-radius maps, exact touch-point lists | no |
| `atelier:execute` | focused implementation from an accepted brief | yes |
| `atelier:review` | adversarial diff review against acceptance criteria | no |

**Hard rules (from repo CLAUDE.md / AGENTS.md):**
- **Hard-remove, never deprecate** — when EMB replaces the hashing default, delete
  the hard `LocalEmbedder` pin; keep hashing only as an explicit offline fallback
  in the factory. No compat shims.
- Every `atelier:code` brief ends with: run the change-surface check from CLAUDE.md
  §"Validation by Change Surface", then **record a trace** referencing the milestone ID.
- **Parallel code agents MUST use `isolation: "worktree"`** and must touch disjoint
  file sets. The orchestrator merges and re-runs the full gate after each merge.
- New capabilities go in `core/capabilities/` — never in `mcp_server.py`/`cli.py`
  (those are dispatchers only).

## 1. Dependency graph & waves

```
W0  (read-only, parallel)        R1 research-models      X1 explore-embeddings-touchpoints
                                        \                      /
W1  EMB ............................ atelier:code (worktree wt-emb) → review → [GATE-EMB]
                                        |
W2  PROOF .......................... atelier:code (M0 baseline can start in W0) → [GATE-PROOF]
                                        |
        ┌───────────────────────────────┼───────────────────┐
W3  RERANK (wt-rerank)          W4  STEM (wt-stem)         (W3,W4 parallel: disjoint files)
   code→review→[GATE-RERANK]      code→review→[GATE-STEM]
        └───────────────────────────────┬──────────────────┘
W5  ROUTE+ (wt-route)  ||  INDEX (wt-index)                (parallel: disjoint files)
   code→review→[GATE-ROUTE]    code→review→[GATE-INDEX]
        |
W6  SPEC (wt-spec)  ← needs EMB + INDEX
   research→code→review→[GATE-SPEC]
```

**Why this order:** EMB first (highest ROI, unblocks honest retrieval numbers);
PROOF second (converts everything to measured); then the two parallelizable
precision/efficiency tracks; routing+freshness; SPEC last (largest, depends on
fresh index + real embeddings).

**Serialization constraint:** EMB, RERANK, SPEC all touch
`code_context/engine.py` + `embedding.py` → they **cannot** run in parallel with
each other. STEM (prefix_cache/router/autopilot), ROUTE+ (model_routing), INDEX
(scip) touch disjoint trees → they **can** parallelize against each other and
against the engine track, in separate worktrees.

---

## 2. Wave 0 — decision spikes (read-only, run in parallel now)

> ✅ **COMPLETE (2026-05-29).** Outputs persisted + orchestrator-verified:
> [`notes/embedding-model-decision.md`](notes/embedding-model-decision.md) (R1)
> and [`notes/emb-touchpoints.md`](notes/emb-touchpoints.md) (X1, line numbers
> re-verified). **W1 is unblocked.**

### R1 — `atelier:research` · model selection memo
**Deliverable:** a ≤1-page memo answering, with citations + exact numbers:
- Default local code-embed model (recommend `nomic-embed-text`), its dim, and
  Ollama pull command; confirm it's in the Ollama library today.
- Best code-specialized local option (`nomic-embed-code` GGUF / Ollama port;
  `Qodo-Embed-1-1.5B`; `jina-code-embeddings-1.5B`) with exact output dims,
  VRAM, license, and CoIR/CodeSearchNet scores.
- Recommended local **cross-encoder reranker** (e.g. `bge-reranker-v2-m3` /
  `jina-reranker`) — served via Ollama or small HF model — with latency notes.
- Whether Anthropic has any embeddings endpoint (expected: no → keep pluggable).
**Output:** write to `docs/plans/world-class-atelier/notes/embedding-model-decision.md`.

### X1 — `atelier:explore` · embedding touch-point map
**Deliverable:** an exact change-set list (file:line) of every place that must
change for EMB:
- All `LocalEmbedder` / `generate_embedding` / `make_embedder` call sites in the
  **code/lineage** path (vs the memory path, which already upgrades).
- The lineage 384-dim pin (`git_history/embedder.py`) and `_LINEAGE_INDEX_VERSION`
  + the stale-reindex flow (`engine.py:_ensure_lineage_ready` ~:6403).
- Where embedding dim is assumed/stored in the SQLite schema, and what a dim
  change breaks (so reindex is correct, not corrupting).
**Output:** `docs/plans/world-class-atelier/notes/emb-touchpoints.md`.

*(R1 and X1 are independent and read-only → launch together.)*

---

## 3. Wave 1 — EMB (neural code embeddings)

**Agent:** `atelier:code`, `isolation: "worktree"` (wt-emb). **Inputs:**
[`notes/embedding-model-decision.md`](notes/embedding-model-decision.md),
[`notes/emb-touchpoints.md`](notes/emb-touchpoints.md), the memory fact
`mem-...embeddings-are-feature-hashing`.

**LOCKED DECISIONS (from W0):**
- **Default model:** `nomic-embed-text` v1.5 (Ollama, **768-dim**, Apache-2.0,
  `ollama pull nomic-embed-text`). **Quality upgrade:** `nomic-embed-code`
  (`manutic/nomic-embed-code`, **3584-dim**, Apache-2.0).
- **`OllamaEmbedder` must apply required prefixes** (`search_query:` /
  `search_document:`; code model `Represent this query for searching relevant
  code: `) and **L2-normalize** — in the embedder, not at call sites.
- **Two invalidations:** bump `_LINEAGE_INDEX_VERSION` (engine.py:155, 1→2)
  **and** give the embedder a new `.name` (`ollama:<model>`) so the
  `embedder_name`-keyed vector cache self-invalidates.
- **Keep the memory path (`make_embedder()`) untouched**; add a separate
  code-path accessor. Ollama-down → hashing fallback (never crash).
- **License:** default to Apache-2.0 nomic models; Qodo (RAIL-M) / Jina
  (CC-BY-NC) are quality-competitive but need legal review for the wedge.
- Verified anchors + ordered change-set live in `notes/emb-touchpoints.md`
  (trust symbols over the draft's line numbers; re-confirm with `node`).

**Scope (delete-don't-deprecate):**
1. NEW `src/atelier/infra/embeddings/ollama_embedder.py` — `OllamaEmbedder(Embedder)`
   POSTing `http://localhost:11434/api/embed`, model `ATELIER_CODE_EMBED_MODEL`
   (default from R1), raises `OllamaUnavailable` on failure.
2. EDIT `infra/embeddings/factory.py` — priority: explicit pin → Ollama reachable
   → OpenAI key → hashing fallback.
3. EDIT `code_context/embedding.py` + `git_history/embedder.py` — replace hard
   `LocalEmbedder` with a shared `code_embedder()` accessor; dynamic dim.
4. EDIT `engine.py` — bump `_LINEAGE_INDEX_VERSION`; store embed dim/model in
   index metadata so a model change forces a clean reindex.
5. NEW unit tests + a retrieval-precision microbench (self-repo or CoIR-style).

**Acceptance / GATE-EMB (orchestrator runs):**
- `uv run pytest tests/core/test_code_context.py -q && make lint && make typecheck` green.
- `M1_lineage` run under **hashing vs nomic-embed-text** → record both pass-rates;
  expect ≥+2 grade points. No dim-mismatch errors after reindex.
- Then `atelier:review` on the diff (embedding correctness, reindex safety,
  offline fallback intact).

---

## 4. Wave 2 — PROOF (make the lift measured)

**Agent:** `atelier:code` (no worktree needed — benchmark/test files only).
**Note:** the **M0 baseline run can start during W0** (it doesn't need EMB).

**Scope:**
1. De-circularise `tests/benchmarks/context_quality/M2_routing.py` — drive from
   **recorded** route-decision traces, not hardcoded `quality_gain` inputs.
2. Run `benchmarks/ab/runner.py` terminalbench on/off, ≥10 tasks ×5 reps, 1 model;
   commit `summary.json` + Wilson CIs to `docs/plans/world-class-atelier/results/`.
3. Stand up the **self-repo eval** from `context-quality-lift/index.md` (30
   multi-file tasks; pass = original PR test suite passes). Run M0, then EMB-on.
4. Replace `bench_cost.py`'s headline with a measured number, or relabel it
   "modeled" in all docs.

**Acceptance / GATE-PROOF:** a single committed table of **real** before/after
numbers (M0 vs EMB) for retrieval precision + task pass-rate + cost. This gate
is what converts the whole audit from "plausible" to "proven."

---

## 5. Waves 3–6 — brief templates

Each uses `atelier:code` (worktree) → `atelier:review` → orchestrator gate.

| Wave | Milestone | Files (disjoint groups) | Parallel with | Proof gate |
|---|---|---|---|---|
| W3 | **RERANK** | NEW `code_context/rerank.py`; EDIT `engine.py` fusion (after RRF ~:2440) | W4 | precision@5 lift on EMB microbench; latency within budget |
| W4 | **STEM** | `prefix_cache/*`, `model_routing/stickiness.py`, `autopilot/*`, new workflow-config schema | W3 | A/B (stem on/off): ≥X% fewer uncached input tokens on a multi-phase task |
| W5a | **ROUTE+** | `model_routing/router.py` (`_estimated_quality_gain_usd`), trace-calibrated estimate + opt-in enforcing wrapper | W5b | trace replay: cost↓, zero quality-tier regression |
| W5b | **INDEX** | `infra/code_intel/scip/watcher.py` (watchdog/inotify) + per-branch keys | W5a | edit→searchable < few sec; branch switch → branch-correct results |
| W6 | **SPEC** | NEW predictor + prefetch cache in `code_context/` | (none) | retrieval latency hidden on N-step tasks; no precision regression |

W6 is preceded by a short `atelier:research` recap of SpecAgent (arXiv 2510.17925).

---

## 6. Copy-paste subagent briefs (Wave 0 & Wave 1)

**R1 — atelier:research**
```
Produce a <=1-page decision memo (with citations + exact numbers) recommending:
(1) a default local code-embedding model for Ollama (verify nomic-embed-text is
in the Ollama library today; give its dim + pull cmd); (2) the best
code-specialized local model among nomic-embed-code (GGUF/Ollama port),
Qodo-Embed-1-1.5B, jina-code-embeddings-1.5B — with exact output dims, VRAM,
license, and CoIR/CodeSearchNet scores; (3) a local cross-encoder reranker with
latency notes; (4) whether Anthropic offers an embeddings endpoint. Write to
docs/plans/world-class-atelier/notes/embedding-model-decision.md. Cite every
number. Do not edit source code.
```

**X1 — atelier:explore**
```
Map every code change required to replace the 384-dim hashing embedder with a
pluggable neural embedder in the CODE + LINEAGE path only (the memory path via
make_embedder() already upgrades, leave it). List file:line for every
LocalEmbedder/generate_embedding/make_embedder call site on the code path; the
lineage dim pin in git_history/embedder.py; _LINEAGE_INDEX_VERSION and the
stale-reindex flow in engine.py; and where embedding dim is stored/assumed in
the SQLite schema (so a dim change reindexes cleanly, not corrupts). Write the
change-set to docs/plans/world-class-atelier/notes/emb-touchpoints.md. Read-only.
```

**W1 — atelier:code (worktree wt-emb)**
```
Implement EMB per docs/plans/world-class-atelier/02-execution-plan.md §3, using
the R1 memo and X1 touch-point map. Add OllamaEmbedder, wire make_embedder()
priority (Ollama->OpenAI->hashing fallback), replace the hard LocalEmbedder pins
in code_context/embedding.py and git_history/embedder.py with a shared
code_embedder() accessor + dynamic dim, bump _LINEAGE_INDEX_VERSION, and store
embed model/dim in index metadata for clean reindex. HARD-REMOVE the pin (no
deprecation shim); keep hashing only as explicit offline fallback. Add unit
tests + a retrieval-precision microbench. Then run:
`uv run pytest tests/core/test_code_context.py -q && make lint && make typecheck`.
Record a trace referencing EMB. Do NOT touch model_routing, scip, or autopilot.
```

---

## 7. Orchestration cadence

1. Launch **R1 + X1** in parallel (read-only, safe).
2. On their return, launch **W1 EMB** in `wt-emb`; in parallel start the **M0
   baseline** portion of PROOF (no worktree).
3. Merge wt-emb after GATE-EMB + review; run full `make pre-commit`.
4. Run **GATE-PROOF** (EMB-on numbers); commit results table.
5. Launch **W3 RERANK (wt-rerank)** and **W4 STEM (wt-stem)** in parallel; merge
   each after its gate (rerank merges last since it also edits engine.py —
   rebase on any engine change from EMB).
6. Launch **W5a ROUTE+ (wt-route)** and **W5b INDEX (wt-index)** in parallel.
7. Launch **W6 SPEC (wt-spec)** last.
8. After every merge: re-run the change-surface gate; if an agent's approach
   fails twice, capture the failing signal and call `rescue` rather than retrying
   a third time.

## 8. Risk controls
- **Worktree discipline** prevents parallel code agents from clobbering shared
  files; the orchestrator is the only merger.
- **Proof gates are blocking** — a wave that can't show its number doesn't merge.
- **Reindex risk (EMB):** dim change must trigger a clean rebuild; X1 verifies
  the schema assumption before W1 writes code.
- **Offline safety:** Ollama-unreachable must fall back to hashing, never crash
  (covered in GATE-EMB).
