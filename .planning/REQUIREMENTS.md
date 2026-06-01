# Requirements: v0.6 World-Class Atelier

**Defined:** 2026-06-01  
**Current Milestone:** v0.6 - World-Class Atelier  
**Previous Milestone:** v0.5 - archived in `.planning/milestones/`  
**Execution rule:** benchmark/proof runs owned outside this session are tracked as external validation, not active implementation work.

## Current State

- `v0.5` is archived and no longer needs active requirements space.
- `v0.6` is now the focused active milestone.
- Phase 15's real-history M4 proof artifact is now recorded; Phase 29 still needs the broader proof bundle.

## Carry-over External Validation

- [x] **SCOPED-01-06**: Scoped pull implementation surfaces landed; validate closure through the real proof artifacts below.
- [x] **CQEVAL-05**: `docs/plans/world-class-atelier/results/m4-repo-history.json` records `commit_hit_rate=1.0`, `precision=0.53`, and `recall=0.8833` on real repo history edits
- [ ] **TBEVAL-02**: TerminalBench-oriented local proof run records an honest pass-rate/cost result or loops back with concrete gaps *(external benchmark artifact pending)*

## v0.6 Requirements

### Phase 28 - World-Class Embedder + Auto-Selection

- [x] **WCA-EMB-01**: `OllamaEmbedder` implementation POSTing to `http://localhost:11434/api/embed` with `nomic-embed-text/code` support
- [x] **WCA-EMB-02**: `OllamaEmbedder` applies required task prefixes and L2-normalization internally
- [x] **WCA-EMB-03**: `make_embedder()` factory priority: explicit pin -> Ollama-reachable -> OpenAI-key -> hashing fallback
- [x] **WCA-EMB-04**: `code_embedder()` accessor replaces hard-pinned `LocalEmbedder` in `code_context/embedding.py` and `git_history/embedder.py`
- [x] **WCA-EMB-05**: Lineage bootstrap worker detects dim change, bumps `_LINEAGE_INDEX_VERSION`, and rebuilds `commit_chunks` automatically
- [x] **WCA-EMB-06**: `reasonblock_embedding_cache` uses `embedder.name` as key, forcing self-invalidation on model switch

### Phase 29 - Real Proof Surfaces + Honest Benchmarks

- [ ] **WCA-PROOF-01**: M2 routing benchmark de-circularized: drives decisions from recorded traces, not hardcoded GAIN inputs *(implementation landed; external proof artifact pending)*
- [ ] **WCA-PROOF-02**: TerminalBench A/B results committed to `docs/plans/world-class-atelier/results/` for >=10 tasks x 5 reps *(external artifact pending)*
- [ ] **WCA-PROOF-03**: Self-repo evaluation suite (30 multi-file tasks) stands up with test-pass/fail gate *(external artifact pending)*
- [ ] **WCA-PROOF-04**: Public README "84% cheaper" headline replaced with a measured empirical delta *(external artifact pending)*

### Phase 30 - Lightweight Reranker Layer

- [x] **WCA-RERANK-01**: `bge-reranker-v2-m3` integration via Ollama or small local HF model
- [x] **WCA-RERANK-02**: Rerank stage inserted after RRF candidate fusion in `code_context/engine.py`
- [x] **WCA-RERANK-03**: Reranking gated by latency budget and candidate count (top 10-30 only)

### Phase 31 - Single-Thread Execution Memory (STEM)

- [x] **WCA-STEM-01**: Phase-aware workflow primitive preserves one conversation/cache warm across explore -> plan -> execute
- [x] **WCA-STEM-02**: `prefix_cache/planner.py` tracks prefix stability across workflow transitions
- [x] **WCA-STEM-03**: Workflow configuration (`vix.json` analogue) exposed via `AutopilotPolicy`
- [x] **WCA-STEM-04**: Multi-model voting enabled for critical planning/review steps within the stem conversation

### Phase 32 - Route+

- [x] **WCA-ROUTE-01**: `quality_gain_usd_estimated` calibrated from real trace outcomes instead of static `rank_delta * 0.001`
- [x] **WCA-ROUTE-02**: Opt-in enforcing routing wrapper/host-hook that executes the recommended model automatically

### Phase 33 - Branch-Aware Incremental Indexing

- [x] **WCA-INDEX-01**: `scip/watcher.py` upgraded to event-driven incremental reindex
- [x] **WCA-INDEX-02**: SCIP index keys are branch-aware, preventing cross-branch context leakage
- [x] **WCA-INDEX-03**: Measured edit-to-searchable latency remains below 5 seconds for the Atelier repo

### Phase 34 - Speculative Retrieval + Prefetch

- [ ] **WCA-SPEC-01**: SpecAgent predictor trained/heuristic on session context predicting next-needed files
- [ ] **WCA-SPEC-02**: Parallel prefetch cache retrieves forecasted files in background before agent tool-calls
- [ ] **WCA-SPEC-03**: Retrieval latency hidden for N-step tasks with no precision regression

### Phase 35 - Reliability Hardening

- [x] **REL-01**: `claim_job` reaps orphaned `running` jobs whose lease exceeds `ATELIER_JOB_LEASE_SECONDS`
- [x] **REL-02**: Consolidation auto-quarantines weak ReasonBlocks instead of leaving them to linger at low rank
- [x] **REL-03**: The stale sweep covers active ReasonBlocks and the `since` behavior is no longer ignored
- [x] **REL-04**: servicectl tick / telemetry surfaces job-queue health so jams are observable

### Phase 36 - Harvest+ Coverage Expansion

- [x] **HARV-01**: Coverage matrix produced for Claude parallel-session transcript surfaces
- [ ] **HARV-02**: Extend harvesting to uncovered sources only after the matrix proves they exist *(blocked on real artifacts)*
- [ ] **HARV-03**: Verify dedup + redaction on newly covered sources *(blocked on real artifacts)*
- [ ] **HARV-04**: Document workflow-agent transcript limitations if per-agent transcripts are unavailable *(blocked on real artifacts)*

### Phase 37 - Dynamic Workflow Sessions

- [x] **FLOW-01**: Ship a `code-audit` dynamic workflow built on Atelier agents
- [x] **FLOW-02**: Ship a `gate-benchmark` workflow with one consolidated verdict
- [x] **FLOW-03**: Package workflows for discovery with tool-allowlist guidance
- [x] **FLOW-04**: Demonstrate adversarial cross-check over the single-pass fixture path

### Phase 38 - Auto-Optimize + Proof Gate

- [x] **OPT-01**: `atelier optimize run` manual CLI diagnoses recent traces + savings and prints candidate optimizations
- [x] **OPT-02**: `JOB_OPTIMIZE` daemon job is registered and crash-safe
- [x] **OPT-03**: install flow prompts for opt-in background optimization and records the choice
- [x] **OPT-04**: Every proposal is gated by non-inferiority proof before opening a PR/issue
- [x] **OPT-05**: Proposals + verdicts are surfaced in telemetry with no auto-merge
- [x] **OPT-06**: Safety defaults keep auto-run OFF unless explicitly enabled
- [x] **NI-01**: Current-code non-inferiority utility reads TerminalBench `runs.jsonl`, computes Wilson/Newcombe bounds, and fails closed on missing or regressing data
- [x] **NI-02**: The benchmark surface emits a single pass/fail non-inferiority verdict consumed by proof artifacts and optimizer gates

## Traceability

| Requirement Group | Phase | Status |
| --- | --- | --- |
| CQEVAL-05 | 15 | Complete |
| TBEVAL-02 | 15 | External validation |
| WCA-EMB-01-06 | 28 | Complete |
| WCA-PROOF-01-04 | 29 | External validation |
| WCA-RERANK-01-03 | 30 | Complete |
| WCA-STEM-01-04 | 31 | Complete |
| WCA-ROUTE-01-02 | 32 | Complete |
| WCA-INDEX-01-03 | 33 | Complete |
| WCA-SPEC-01-03 | 34 | Pending |
| REL-01-04 | 35 | Complete |
| HARV-01-04 | 36 | HARV-01 complete; HARV-02-04 blocked |
| FLOW-01-04 | 37 | Complete |
| OPT-01-06 / NI-01-02 | 38 | Complete |
