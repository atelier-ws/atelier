# World-Class Atelier — Second Deep Audit (code-verified) & Real Frontier Plan

> Created 2026-05-29. **Supersedes [`00-deep-audit.md`](00-deep-audit.md).**
> The first audit was right to correct `grounding.md` ("M1/M2 missing" was false),
> but it then over-corrected: it labelled capabilities "✅ built+wired" from a
> single `file:line` reference **without proving they work or assessing their
> quality**, repeated a hallucinated embedding stack ("nomic-embed-text/local"),
> called a *simulated* cost number "measured," called real benchmark harnesses
> "stubs," and never looked at Eval at all.
>
> This audit is **code-verified**: every claim below carries a `file:line`, a
> test result I actually ran, or a web source I actually fetched. Where a claim
> cannot be proven today, it is marked **UNPROVEN** rather than "built."

## Methodology

- **Internal**: direct reads of the implementing code (not just the cited line),
  call-graph checks (`callers`/`node`) to confirm wiring, and **tests executed**
  this session. Test runs quoted verbatim.
- **External**: live `WebFetch`/`WebSearch` of Eval (getvix.dev, HN Show HN,
  feature posts) **and** a fresh pass on Augment (Context Engine MCP, real-time
  index, Prism) — not a re-read of the stale memo.
- Confidence tags: ✅ verified-in-code · 🧪 verified-by-running-tests ·
  🟡 real-but-unproven · 🔴 genuine gap · ⚪ deliberate non-goal.

---

## 0. TL;DR — the five headline corrections

1. **Embeddings are the load-bearing gap, and it is bigger *and cheaper to fix*
   than the first audit said.** Code + lineage semantic search runs on
   **384-dim feature *hashing*** by default (`infra/embeddings/local.py`), not
   "generic nomic-embed-text." There is **no local neural embedding backend at
   all** — only hashing or cloud OpenAI. So default "semantic" code search is
   lexical overlap in disguise. **But** the fix is ~1 day, not "months of R&D":
   pull a code-trained model from HuggingFace and serve it via Ollama (§6).
2. **The cost/quality lift is *modeled*, not *measured*.** `benchmarks/mcp_tools/
   bench_cost.py` is a **simulation** (`_simulate_naive`/`_simulate_atelier` with
   hardcoded turn profiles); M2's routing benchmark is **circular** (it hardcodes
   the very `quality_gain_usd_estimated` inputs that make its assertion pass);
   the real terminalbench A/B harness exists but has **zero result artifacts on
   disk**. "84% cheaper" is plausible and internally consistent — **not proven
   end-to-end.**
3. **Lineage and cache-aware routing are genuinely built, wired, and tested** —
   *more* real than the first audit even implied (real Haiku summariser, RRF
   merge into live results, 12 passing routing tests). Their weakness is
   **quality/proof**, not existence.
4. **Augment is now a direct competitor on Atelier's exact turf.** They shipped
   the **Context Engine over MCP (Feb 2026)** with published external lift
   (+80% on Claude Code/Opus 4.5, +71% on Cursor). "Augment is a closed product"
   is no longer true; they plug into the same hosts Atelier does and publish
   numbers Atelier has not.
5. **Eval (getvix.dev) attacks Atelier's home turf (token efficiency) with a
   technique Atelier lacks: the "stem agent"** — one generic agent that keeps the
   prompt cache warm across explore→plan→execute instead of spawning
   prompt-distinct sub-agents — claiming 50% cheaper / 40% faster than Claude
   Code. Atelier's autopilot (M5) is *not* this.

---

## 1. What the first audit got wrong (corrections)

| First-audit claim | Reality (code-verified) | Evidence |
|---|---|---|
| Embeddings are "generic (nomic-embed-text/local)" | **Feature hashing, 384-dim.** No nomic, no sentence-transformers anywhere. | `infra/embeddings/local.py` (`_DEFAULT_MODEL="hashing"`); `grep` for `nomic/sentence_transformers` → none in `src/atelier` |
| Code-trained embeddings = "high effort (R&D), months — defer" | **~1-day integration.** SOTA code embedders are downloadable (Qodo/Nomic/Jina) and run on Ollama locally. | §6; HF + Ollama sources |
| Cost A/B "already green (84%)" / "measured" | **Simulated**, not measured. | `benchmarks/mcp_tools/bench_cost.py` = `_simulate_naive`/`_simulate_atelier` |
| M1/M2 benchmarks are "stubs" | M1 is a **real 258-line eval** (10 ground-truth commits, ≥7/10 gate); `benchmarks/ab/` is a **full terminalbench A/B harness** (Wilson CI, PR-replay, publish). | `tests/benchmarks/context_quality/M1_lineage.py`; `benchmarks/ab/runner.py` |
| (M2 implied to prove cost win) | M2 is **circular** — it injects the `quality_gain_usd_estimated` values that force the ≥10% result. | `tests/benchmarks/context_quality/M2_routing.py:_trace()` |
| scip watcher = "signature/mtime refresh-on-access" (correct, but understated) | Even thinner: a 1-method mtime+size **comparator**; *no* filesystem watching, *no* reindex trigger. | `infra/code_intel/scip/watcher.py` (whole file is ~25 LOC) |
| Eval not considered | Eval is a direct token-efficiency competitor with a concrete cache technique Atelier lacks. | §2.1 |
| Augment = "closed product" durable advantage | Augment now ships an **MCP context engine** into Claude Code/Cursor — same integration surface as Atelier. | §2.2 |

---

## 2. Competitor deep-dive

### 2.1 Eval (getvix.dev) — the token-efficiency threat the first audit missed

"Sleek, Fast and Token Efficient AI Coding Agent." Benchmarked by its author at
**~50% cheaper and ~40% faster than Claude Code** on 7 scenarios × 5 reps with
*identical prompts and models* (plans + diffs published for inspection).

Mechanisms (from getvix.dev + the Show HN):

- **Virtual-filesystem minification** — the agent operates *exclusively* on a
  minified view of source. **Atelier already does this** (minify/compact/outline)
  and arguably better — so this is parity, not a gap.
- **"Stem agent" — the real differentiator.** Instead of spawning
  prompt-distinct Explore/Plan/Execute sub-agents (each a cache miss, since the
  system prompt changes), Eval runs **one generic agent** told up-front that
  multiple phases will occur; each phase is introduced by a *user* message. The
  planning phase therefore reuses the **cached** exploration history. Cache
  reuse across phases is the lever (a cache miss costs ~10× a hit).
- **Workflow config (`eval.json`/settings)** — per-step context-sharing control,
  structured (JSON) outputs, and **voting on critical steps**, all in one
  consolidated agent rather than sub-agent fan-out.

**Why it matters to Atelier:** Atelier's whole pitch is token efficiency. Eval
claims a bigger headline number with a *structural* technique (phase-cache
continuity) that Atelier does **not** implement. Atelier has the substrate
(`prefix_cache/planner.py`, router stickiness) but no "keep one
conversation/cache warm across phases" primitive. See GAP-5.

### 2.2 Augment Code (refreshed) — now an MCP context-server competitor

- **Context Engine over MCP (Feb 2026)** — Augment exposed its context engine as
  an MCP server. Published external lift: **Claude Code + Opus 4.5 = +80%
  quality; Cursor + Opus 4.5 = +71%; completeness +60%, correctness 5×.** This
  is the *same integration surface and value proposition as Atelier* — and they
  have public numbers Atelier lacks.
- **Real-time, per-developer, branch-aware index** — dependency graph + commit
  history + embeddings, thousands of files/sec on GCP, **custom paired
  embedding+retrieval models** (trained together), now including PR history.
- **Prism routing (fresh numbers)** — planner reads each turn, switches model
  only when expected quality gain > cache-eviction cost; sticky across tool
  follow-ups; no mid-turn override. Prism(GPT+Kimi) within **0.7pp** of GPT-5.5
  at **~12% cheaper**; Prism(Claude+Gemini) within **2.3pp** of Opus 4.7 at
  **~7% cheaper**; 20–30% average savings; evaluated on 731 SWE-bench Pro
  instances (the "worst case for routers").
- **Cosmos** = their org-shared "Agent OS" (team knowledge).

**Net:** Atelier's *architecture* mirrors Augment's quality levers (lineage,
cache-aware routing, MCP delivery) but trails on **(a)** embedding quality
(paired custom models vs hashing) and **(b)** *published, measured* lift.

---

## 3. Atelier's true state — verified capability ledger

Each row: **Real?** (code exists & is non-trivial) · **Wired?** (reached on the
live path) · **Works?** (tests run this session) · **Proven?** (empirical lift
exists) · **Quality** notes.

### 3.1 Context lineage (M1)
- **Real ✅ / Wired ✅ / Works 🧪 / Proven 🟡.**
- Pipeline: walk ≤500 commits → **real LLM summary** (Haiku via `internal_llm.chat`,
  thoughtful 80–120-word prompt covering objective/files/search-terms — *not*
  raw commit messages) → embed summary+files → `commit_chunks` (with
  `index_version` for staleness) → query embed + cosine → **RRF-merged** into
  live search results.
- Evidence: summariser `infra/code_intel/git_history/summarizer.py`; bootstrap
  `code_context/engine.py:6390` (`_ensure_lineage_ready`) called from
  `_ensure_indexed` (engine.py:3827) **and** the post-commit hook; **RRF merge
  confirmed** at engine.py:2434 (`reciprocal_rank_fuse(lexical, semantic +
  commit_hits)`).
- **Quality caveat:** the summary embedding rides the **hashing** embedder
  (`git_history/embedder.py` hard-pins `LocalEmbedder`, dim 384). So lineage
  recall is lexical unless `ATELIER_EMBEDDING_PROVIDER=openai`. **UNPROVEN:** the
  ≥7/10 M1 gate has not been run with a live backend (no artifacts; test skips
  without bootstrap+key).

### 3.2 Cache-aware routing (M2)
- **Real ✅ / Wired ✅ / Works 🧪 (12 passed in 0.22s) / Proven 🔴.**
- `model_routing/router.py`: heuristic tier score (tool/verb/output/errors/phase)
  + a genuine cache layer in `recommend()` — **stickiness** (preserve route
  while sticky), **cache-eviction-cost vs quality-gain** tradeoff via
  `cache_cost.cache_eviction_cost_usd(prior_plan, current_plan, pricing)`, and a
  `route_decision` event sink.
- Wired: `recommend()` is consumed by the `route` MCP tool
  (`mcp_server.py:1439`), `_emit_model_recommendation` (:5037), the CLI
  (`cli/app.py:3362`), the cross-vendor advisor, and **lesson-binding**
  (route-preference lessons reshape routing). 8 cache-aware unit tests pass.
- **Two real weaknesses:** (1) **advisory only** — it *recommends*; nothing flips
  the host model automatically (Prism *switches*). (2) The default quality-gain
  estimate is a **magic number** — `rank_delta * 0.001`
  (`router.py:_estimated_quality_gain_usd`) — uncalibrated unless the caller
  passes an explicit value. So the Prism-equivalent decision is unproven and
  un-tuned. M2's "10% cost reduction" is circular (§1).

### 3.3 Embeddings (cross-cutting)
- **Two systems, very different quality:**
  - **Memory layer** (`lesson_promotion`, `archival_recall`, `context_reuse`,
    `memory_arbitration`, runtime engine) uses `infra/embeddings/factory.make_embedder()`
    → **upgrades to real OpenAI** `text-embedding-3-small` when `OPENAI_API_KEY`
    is set; falls back to hashing. ✅ acceptable.
  - **Code + lineage layer** (`code_context/embedding.py`, `git_history/embedder.py`)
    is **hard-pinned to `LocalEmbedder`** (hashing, 384-dim), upgradable to
    OpenAI *only* via `ATELIER_EMBEDDING_PROVIDER=openai` (which then truncates
    1536→384). **No local neural option exists.** 🔴 This is GAP-1 and the
    single highest-ROI quality fix.

### 3.4 Verification / counterexample (M3), scoped pull (M4), autopilot (M5)
- **Real ✅ / Wired ✅ / Works 🧪 — 57 passed in 0.88s** across
  `tests/core/test_verification.py`, `test_scoped_context.py`, `test_autopilot.py`,
  `test_routing_verifier.py`, `test_cost_quality_proof_gate.py`,
  `benchmarks/mcp_tools/bench_cost.py`.
- `verification/` (budget, checks, counterexample), `scoped_context/` (pull,
  prune, models), `autopilot/` (policy, factory) are all substantive modules.
  Counterexamples are wired to the post-edit hook (this session's own
  system-reminder confirms the surface).
- **But autopilot ≠ Eval stem agent.** `autopilot/policy.py` is a *trigger→behavior*
  map (session_start→warm, user_prompt→scoped_inject gated by a code-signal
  regex, post_edit→counterexamples). It chooses *what context to inject when* —
  it does **not** preserve one conversation/cache across phases. See GAP-5.
- **Proven 🔴:** the M3/M4/M5 *quality* gates (`M3_verification.py` etc.) and the
  whole-plan +15pp self-repo eval have not been run.

### 3.5 Index freshness
- **🔴 gap (confirmed, understated before).** `scip/watcher.py` is a ~25-LOC
  mtime+size signature comparator with a callback — *no* inotify/watchdog, *no*
  reindex trigger, *not* branch-aware. "Real-time within seconds" (Augment) is
  not approximated.

### 3.6 Things that are genuinely ahead (protect)
- Vendor-neutral MCP substrate (Claude/Codex/Gemini); loop-detection/rescue
  (`loop_detection/rescue.py`); cross-vendor memory + lesson promotion;
  local-first; checkpoints/rollback. These are real and differentiated.

---

## 4. The real gaps (prioritized by impact ÷ effort)

| # | Gap | Impact | Effort | Why it's real (evidence) |
|---|---|---|---|---|
| **G1** | **Neural code embeddings (replace hashing)** | **Very high** | **~1 day** | `local.py` hashing is default for *all* code/lineage retrieval; SOTA local models exist (§6) |
| **G2** | **Empirical proof program** (run M1, A/B, self-repo eval) | **High (it's the whole "world-class" claim)** | 3–5 days | bench_cost simulated; M2 circular; zero A/B artifacts |
| **G3** | **Cross-encoder reranker** | High | 2–3 days | only heuristic RRF today; "relevant-but-unhelpful" not filtered |
| **G4** | **Eval-style phase-cache continuity ("stem" workflow) + voting** | High (token efficiency = our pitch) | 1–2 wks | autopilot ≠ stem agent; prefix_cache substrate unused for this |
| **G5** | **Calibrated + enforcing routing** | Medium-high | 3–4 days | quality-gain = `rank_delta*0.001`; advisory only |
| **G6** | **Continuous / branch-aware index** | Medium | 3–5 days | watcher is mtime-poll, not event-driven |
| **G7** | **Speculative / forecasted retrieval (SpecAgent)** | High | 2–4 wks | reactive retrieval only; novel differentiator |
| G8 | Enterprise/security surface | Commercial | ongoing | tracked in commercial-wedge W0–W7 |
| — | Multimodal / Completions | n/a | — | ⚪ deliberate skip (Augment sunsetting Completions; multimodal not a quality lever) |

---

## 5. Exact plan (sequenced, with proof gates)

> Rule for every milestone: **it is not "done" until a recorded benchmark shows
> the claimed delta.** No more "built+wired" without a number.

### Phase A — Embeddings + Proof (the foundation; do first)

**EMB (G1) — neural code embeddings via Ollama.** *~1 day.*
1. Add `infra/embeddings/ollama_embedder.py`: `OllamaEmbedder(Embedder)` POSTing
   to `http://localhost:11434/api/embed`, model from `ATELIER_CODE_EMBED_MODEL`
   (default `nomic-embed-text`); raise `OllamaUnavailable` on failure. (Reuse the
   existing `ollama_client.py` pattern.)
2. Insert into `make_embedder()` priority: pin → Ollama-reachable → OpenAI-key →
   hashing fallback (keeps local-first + offline-safe).
3. Replace the hard `LocalEmbedder` imports in `code_context/embedding.py` and
   `git_history/embedder.py` with a shared `code_embedder()` accessor; make the
   stored dimension dynamic and **bump `_LINEAGE_INDEX_VERSION` on dim change**
   (the stale-reindex path already exists — engine.py:6403).
4. **Proof gate:** run `M1_lineage` (≥7/10) under hashing vs `nomic-embed-text`
   vs `nomic-embed-code`; record the step-change. Add a small CoIR-style /
   self-repo retrieval-precision microbench. *Acceptance: ≥+2 grade points on
   M1 and a measurable precision lift; no dim-mismatch errors.*

**PROOF (G2) — make the lift real.** *3–5 days.*
1. De-circularise M2: drive it from **recorded** route-decision traces, not
   hardcoded `quality_gain` inputs.
2. Run the existing `benchmarks/ab/` terminalbench harness on/off for ≥10 tasks
   ×5 reps with one model; commit `summary.json` + Wilson CIs under
   `docs/plans/world-class-atelier/results/`.
3. Stand up the **whole-plan self-repo eval** described in
   `context-quality-lift/index.md` (30 multi-file tasks; pass = original PR test
   suite passes). Baseline M0, then toggle EMB/M1/M3/M4. *Acceptance: a single
   committed table of real numbers; replace bench_cost's simulated headline with
   a measured one (or keep it but label it "modeled").* 

### Phase B — Retrieval precision

**RERANK (G3).** *2–3 days.* Add a rerank stage after RRF over the top-N
candidates using a **local cross-encoder** (e.g. `bge-reranker`/`jina-reranker`
via Ollama or a small HF model), gated by latency budget. Plugs into
`code_context/engine.py` candidate fusion (right after the RRF at :2440).
*Acceptance: precision@5 lift on the EMB microbench; latency within budget.*

### Phase C — Token-efficiency parity with Eval

**STEM (G4).** *1–2 weeks.* Ship a **phase-aware workflow primitive** that keeps
one conversation/cache warm across explore→plan→execute (the Eval lever), using
`prefix_cache/planner.py` to track prefix stability and router stickiness to
avoid mid-phase model flips; expose per-step context-sharing + **voting on
critical steps** as config (the `eval.json` analogue), choreographed by autopilot.
*Acceptance: A/B (STEM on/off) shows ≥X% fewer uncached input tokens on a
multi-phase task — measured, to answer Eval's 50% claim head-on.*

### Phase D — Routing maturity & freshness

**ROUTE+ (G5).** *3–4 days.* Replace the `rank_delta*0.001` quality-gain with an
estimate **calibrated from recorded trace outcomes**; add an opt-in *enforcing*
path (route-and-execute wrapper / host hook) so routing isn't purely advisory.
*Acceptance: replay shows cost↓ with no quality-tier regression on real traces.*

**INDEX (G6).** *3–5 days.* Upgrade `scip/watcher.py` to event-driven
(watchdog/inotify) incremental reindex + per-branch index keys. *Acceptance:
edit-to-searchable latency < a few seconds on this repo; branch switch yields
branch-correct results.*

### Phase E — The differentiator

**SPEC (G7).** *2–4 weeks.* Speculative/forecasted retrieval: predict
next-needed files from the call graph + recent edits, prefetch + cache in
parallel. Atelier already has the graph (SCIP/`call_graph`) and a budget packer;
the missing pieces are the predictor and the prefetch cache. *Acceptance:
retrieval latency hidden on N-step tasks; no precision regression.*

---

## 6. Embeddings deep-dive — answering "is there a HF code model we can run on Ollama?"

**Yes — and it makes training our own unnecessary for now.** Replace hashing
with an existing, openly-licensed, code-trained model served locally. Anthropic
has **no first-party embeddings endpoint** today (they recommend Voyage AI), so
the right design is a **pluggable `Embedder`** that defaults local and can adopt
a future Claude/Voyage embed model without code change.

| Model | Code quality | Local? | License | Use as |
|---|---|---|---|---|
| **`nomic-embed-text`** | Beats `text-embedding-3-small`; 768-dim, long-ctx | **In Ollama library today** (`ollama pull nomic-embed-text`) | Apache-2.0 | **Default drop-in** — zero friction, massive upgrade over hashing |
| **`nomic-embed-code`** (7B) | **SOTA CodeSearchNet**; beats Voyage-Code-3 & OpenAI-3-Large | **GGUF + Ollama community port** exist | Apache-2.0 | Best code-specialized local; needs more VRAM, reindex |
| **`Qodo-Embed-1-1.5B`** | **CoIR 68.53 > OpenAI-3-large 65.17** | via sentence-transformers / GGUF | OpenRAIL-M | Strong small code model |
| **`jina-code-embeddings-1.5B`** | ≈ voyage-code-3 (79.2%); 0.5B also strong | local | apache/cc | Efficient code retriever |
| Voyage `voyage-code-3` | Top-tier | ❌ cloud API | — | Optional cloud ceiling |

**Integration cost:** small. Atelier already has `ollama_client.py`, an
`Embedder` interface, a `make_embedder()` factory, and a stale-reindex mechanism.
The only real work is the `OllamaEmbedder` class, the factory wiring, unpinning
the lineage 384-dim assumption, and a one-time reindex (cosine is dim-agnostic;
all stored vectors must share one dim, so a dim change ⇒ `index_version` bump ⇒
rebuild). **This single change likely moves M1 and general code-search recall
more than any other item in this audit.**

---

## 7. Durable advantages to protect

Vendor-neutral MCP substrate · loop-detection/rescue · cross-vendor memory +
lesson promotion · local-first · checkpoints/rollback · measured (once we run it)
cost optimization. Augment is single-vendor-cloud; Eval is single-agent. Atelier's
portability is the moat — **but only if the lift is proven** (Phase A).

## 8. Confidence & what I did NOT fully verify

- ✅ Verified by reading + tests run: hashing embedder; lineage summariser +
  RRF merge + wiring; routing logic (12 tests) + its consumers; M3/M4/M5
  modules (57 tests); bench_cost is a simulation; M2 circularity; watcher
  mechanism; no neural-local embedder exists.
- 🟡 Not exhaustively audited (flagged honestly): whether the commit *summary
  text* reaches the agent in a high-signal field (M1 grading leans on SHA-prefix
  + keyword overlap of `signature`); exact dims of the 7B code models (assume
  reindex either way); `cache_cost.py` math depth vs Prism; whether any host
  *acts* on the route recommendation in practice.
- Next focused audit: run Phase-A proofs and paste real numbers here, then
  re-grade every 🟡 to ✅/🔴 based on data.

## Sources

- **Eval**: getvix.dev; Show HN (`news.ycombinator.com/item?id=47680184`); feature
  writeups (stem agent / eval.json workflow / cache reuse across phases).
- **Augment**: Context Engine MCP (Feb 2026, +80%/+71% external lift); real-time
  index blog; Prism routing blog (731 SWE-bench Pro, 0.7pp/2.3pp, ~7–12%).
- **Embeddings**: HF `nomic-ai/nomic-embed-code(-GGUF)`; `ollama.com/library/nomic-embed-text`
  + `manutic/nomic-embed-code`; `Qodo/Qodo-Embed-1-1.5B`; jina-code-embeddings
  (0.5B/1.5B); CoIR benchmark (ACL 2025, arXiv 2407.02883).
- **Internal**: file:line refs throughout; test runs quoted inline.
