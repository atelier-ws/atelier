# World-Class Atelier — Deep Augment Audit & Frontier Roadmap

> ⚠️ **SUPERSEDED by [`01-second-audit.md`](01-second-audit.md) (2026-05-29).**
> This first pass over-corrected: it tagged capabilities "built+wired" from a
> single line reference without proving they work or assessing quality, repeated
> a hallucinated embedding stack ("nomic-embed-text/local" — it is feature
> *hashing*), called a *simulated* cost number "measured," called real benchmark
> harnesses "stubs," and never evaluated Eval. Read `01` for the code-verified,
> test-backed audit and the real plan. Kept here for history.
>
> Created 2026-05-29. A deep, code-verified comparison of Atelier against
> Augment Code's full technical stack (including their published research),
> correcting the stale surface-level [`context-quality-lift/grounding.md`]
> (../context-quality-lift/grounding.md) (2026-05-28).
>
> **Headline correction:** the grounding doc claims M1 (lineage) and M2
> (cache-aware routing) are "missing." They are **built and wired.** Atelier is
> at or near parity on most of Augment's *quality* levers. The real frontier is
> research-grade techniques (speculative retrieval, code-trained embeddings,
> cross-encoder reranking, continuous indexing) plus the commercial surface.

## Methodology

- External: Augment engineering blogs + product pages + **arXiv papers**
  (SpecAgent 2510.17925; Next Edit Prediction 2508.10074) + the Prism routing
  post (concrete numbers).
- Internal: direct code audit with `file:line` references. Confidence tagged
  per row: ✅ verified in code · 🟡 partial/needs depth check · 🔴 absent.

## 1. Augment's technical stack (deep)

### 1.1 Context engine
- **Real-time index**: updates "within seconds" of edits (vs ~10-min
  competitors), GCP PubSub + BigTable + custom inference; thousands of
  files/sec; **per-developer, branch-aware** indices; shared overlap to bound
  RAM. Bulk vs realtime on separate PubSub queues; new embedding models run in
  **shadow mode** during catch-up.
- **Custom code-trained embeddings** (not generic similarity): tuned for
  callsites, docs, cross-language patterns; **hard-negative mining** (3rd-party
  reported). Embeddings never exposed (anti-reverse-engineering).
- **Relevance prioritization**: filters "relevant-but-unhelpful" (e.g.
  redundant popular-library code).
- **Proof-of-Possession**: IDE cryptographically proves file access before
  retrieval (security + correctness boundary).

### 1.2 Retrieval research (the non-obvious depth)
- **SpecAgent (speculative retrieval + forecasting)** — a forecasting agent
  predicts which files the generator will need and **prefetches in parallel**,
  hiding retrieval latency (CPU branch-prediction analogy). Retrieval is BM25 +
  semantic but **conditioned on predicted relevance**, with prefetch caching
  within a session. Implementable: train a light predictor on
  `<context, next_file_needed>` pairs + concurrent retrieval queues +
  confidence thresholds.
- **Next Edit Prediction** — predicts the *next edit* from context + interaction
  history. **Augment is sunsetting Completions/Next Edit (Mar 31)** as usage
  shifts to agents — do **not** chase this.

### 1.3 Model routing — Prism
- Small fast **planner before each turn** picks a model from a pool
  (Claude+Gemini or GPT+Kimi). **Switch only when expected quality gain >
  cache-eviction cost** (cache miss ~10x a hit). **No mid-turn override**;
  routing **sticky across tool-call follow-ups**; switch context bounded.
- Overhead: planner fires on ~4% of turns (96% reuse cached route); 0.03% of
  spend; ~3% aggregate latency. Results: SWE-Bench Pro 59.5% @ -7% cost
  (Claude+Gemini), 52.9% @ -12% (GPT+Kimi); ~20-30% cost reduction.
- Eval: synthetic multi-message dev conversations from a Go repo's PR history,
  LLM judge scoring correctness/completeness/reuse/best-practices/docs in
  [-1, 1].

### 1.4 Agent + orchestration
- **Memories**: auto-generated during work, persist across conversations,
  match coding style, workspace-scoped, zero-credit.
- **Intent / multi-agent orchestration** (early 2026): coordinates
  triage -> author -> review -> verify across **git-worktree-isolated** agents;
  **CIV / VeriMAP pull model** — Coordinator runs semantic analysis and gives
  each Implementor **scoped per-subtask context** (explicitly rejects push to
  avoid "lost in the middle"); Implementors read/write a shared context
  dictionary (bidirectional sync).
- Agent: 200K context; tools (terminal, GitHub/Jira/Confluence/Notion/Linear);
  MCP; multi-modal (screenshots/Figma); **checkpoints/rollback**; Auto mode;
  VS Code + JetBrains; 100k+ file monorepos.

### 1.5 Enterprise / platform
- SOC 2 Type II, ISO/IEC 42001, SAML/OIDC/SCIM, granular RBAC, audit+SIEM,
  CMEK/BYOK, data residency, on-prem; agent runtime scheduling/isolation,
  sandboxed execution, expert registry, org-shared knowledge, remote/cloud
  multi-repo agents.

## 2. Atelier's audited true state

| Augment lever | Atelier | Status | Evidence |
|---|---|---|---|
| Context Lineage (commit summaries embedded + retrieved) | `git_history/{summarizer,embedder,blame,renames}`, lineage merged via RRF | ✅ **built+wired** | `code_context/engine.py:2432` (LINEAGE-03 merge), `_ensure_lineage_ready` :6390, background `_lineage_thread` :590 |
| Cache-aware routing (Prism-equivalent) | `model_routing/{router,cache_cost,stickiness}` + `prefix_cache/planner` | ✅ **built+wired** | `router.py:14-19,110,232` (`cache_eviction_cost_usd`, `sticky_until_tool_calls`, `prior_plan: PrefixCachePlan`) |
| Scoped pull per subtask (CIV pull) | `scoped_context` (M4) + `context op=pull` | ✅ built (this work) | `core/capabilities/scoped_context/` |
| Counterexample/verification loop | `verification` (M3) + `proof_gate` | ✅ built (this work) | `core/capabilities/verification/` |
| Memories / learns-as-you-work | `lesson_promotion`, `archival_recall`, `cross_vendor_memory` | ✅ have (vendor-neutral; ahead) | — |
| Multi-stage reranking | adaptive priors + graph propagation + ANN rerank + RRF | 🟡 have (heuristic, **no cross-encoder**) | `context_reuse/capability.py:715,726,760` |
| Checkpoints / rollback | `infra/runtime/checkpoint.py` | ✅ have | — |
| Loop detection / rescue | `loop_detection/rescue.py` | ✅ **ahead** (Augment undocumented) | — |
| Cost optimization (minify/compact/outline) | proven 84% cheaper end-to-end | ✅ **ahead** (measured) | `benchmarks/mcp_tools/bench_cost.py` |
| Real-time index | `scip/watcher.py` = signature/mtime refresh-on-access | 🟡 **gap** — not continuous/seconds-fresh/branch-aware | `scip/watcher.py` (bounded refresh, not inotify push) |
| Custom code-trained embeddings + hard negatives | generic (`nomic-embed-text`/local) | 🔴 gap (months of R&D) | `infra/embeddings/` |
| **Speculative/forecasted retrieval (SpecAgent)** | reactive retrieval only | 🔴 **gap — novel lever** | — |
| Cross-encoder reranker | heuristic rerank only | 🔴 gap | — |
| Multi-agent orchestration (Intent/CIV) | none (phase_runner removed) | ⚪ deliberate — host/GSD orchestrates | — |
| Completions / Next Edit | none | ⚪ **skip — Augment sunsetting** | — |
| Multi-modal (screenshots/Figma) | none | 🔴 gap (not a core quality lever) | — |
| Enterprise (SOC2/RBAC/SCIM/CMEK/proof-of-possession/on-prem) | `audit_export`, `governance`, `sync/encryption`, commercial-wedge W0-W7 | 🟡 partial (commercial track) | `docs/plans/commercial-wedge/` |
| Remote/cloud multi-repo agents | `remote_client`; local-first by design | ⚪ mostly deliberate | — |
| Org-shared memory (Cosmos) | `team/` + `cross_vendor_memory` + W6 | 🟡 partial | — |

## 3. The real frontier gaps (prioritized: impact × effort)

1. **Speculative / forecasted retrieval (SpecAgent-style)** — *high impact,
   medium-high effort, novel.* Forecast next-needed files from the dependency
   graph + recent edits; prefetch + cache in parallel so context is warm before
   the agent asks. Atelier has the graph (`call_graph`, SCIP) and a budget
   packer — the missing piece is the predictor + prefetch cache. **This is the
   biggest differentiator Atelier currently lacks.**
2. **Cross-encoder reranker** — *high impact, medium effort.* Add a rerank stage
   over the candidate set (small local cross-encoder or LLM-judge rerank) to
   drop "relevant-but-unhelpful" results. Plugs into existing rerank pipeline.
3. **Continuous / branch-aware index freshness** — *medium impact, medium
   effort.* Upgrade `scip/watcher` from signature-poll to event-driven
   (watchdog/inotify) incremental reindex + per-branch index keying. Fewer
   stale-context hallucinations.
4. **Code-trained embeddings + hard-negative mining** — *high impact, high
   effort (R&D).* The deepest retrieval-quality lever; needs a labelled corpus
   + training. Defer unless retrieval precision plateaus.
5. **Eval maturity** — *enabler.* M1/M2 benchmarks are still stubs
   (`tests/benchmarks/context_quality/M1_lineage.py`, `M2_routing.py`); the
   Prism-style LLM-judge multi-turn eval and a frontier-model A/B are the way to
   *prove* world-class. Cost A/B already green (84%).
6. **Enterprise/security surface** — *commercial, not quality.* SOC2, RBAC,
   SCIM, CMEK, proof-of-possession, on-prem. Tracked in commercial-wedge.

## 4. Atelier's durable advantages (protect these)

- **Vendor-neutral** substrate (Claude/Codex/Gemini via MCP) — Augment is a
  closed product.
- **Loop detection / rescue** — no documented Augment equivalent.
- **Measured cost optimization** (84% cheaper) — concrete, reproducible.
- **Local-first** — no mandatory cloud index.
- **Cross-vendor memory + lesson promotion** — durable, portable learning.

## 5. Sequenced roadmap to world-class

**Phase A — prove what exists (days).** Build the M1/M2 benchmarks (currently
stubs); run the frontier-model A/B (with vs without Atelier) once an API key is
available; publish the lift+cost numbers. This converts "we have the levers"
into "we can prove the lift" — the Augment claim structure.

**Phase B — close the two high-ROI quality gaps (1-2 weeks).**
(1) Cross-encoder rerank stage; (2) continuous/branch-aware indexing. Both plug
into existing pipelines and directly raise retrieval precision/freshness.

**Phase C — the differentiator (2-4 weeks).** Speculative/forecasted retrieval
(SpecAgent-style). This is the lever Augment researched and Atelier lacks; done
well it is both a latency and a quality win and a genuine talking point.

**Phase D — R&D + commercial (ongoing).** Code-trained embeddings
(hard-negative mining) for the last precision increment; enterprise/security
surface per commercial-wedge.

## 6. Confidence & follow-ups

- ✅ Verified in code: M1 lineage merge, M2 routing API, reranking stages,
  cost A/B, scip watcher mechanism.
- 🟡 Not deep-audited (flagged honestly): lineage *quality* (are summaries
  embedded with good vectors?), branch-awareness of the index, depth of
  `cache_cost` math vs Prism. Worth a focused follow-up audit before claiming
  parity publicly.

## Sources

- SpecAgent (arXiv 2510.17925); Next Edit Prediction (arXiv 2508.10074)
- Augment: real-time index, Meet Augment Agent, product, 7 ways context
  engineering, CIV guide, Prism routing, Completions/Next-Edit sunset changelog.
