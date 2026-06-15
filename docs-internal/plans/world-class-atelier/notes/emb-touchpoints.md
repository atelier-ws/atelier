# Embedding Touch-Points & Reindex Plan (W0/X1) — orchestrator-verified

> W0 deliverable. Drafted by `atelier:explore`; **line numbers re-verified by the
> orchestrator 2026-05-29.** The explore draft's `vector.py` line numbers were
> wrong (it cited `generate_embedding` at 42–50; it is **219–230**). All the
> *behaviors* it described are real and confirmed below.
>
> **Rule for W1: trust symbol names, not the draft's line numbers. Re-confirm
> each anchor with `mcp__atelier__node` before editing.**

## Authoritative anchors (verified this session)

| File | Symbol / thing | Verified location |
|---|---|---|
| `infra/embeddings/local.py` | `LocalEmbedder` (`_DEFAULT_MODEL="hashing"`, `_DEFAULT_DIM=384`); `.embed()` delegates to `generate_embedding(dim=384)` | whole file ~27 LOC |
| `infra/storage/vector.py` | `cosine_similarity` | **120–142** |
| `infra/storage/vector.py` | **dim-mismatch guard** `raise ValueError("Vector dimension mismatch ...")` | **125–126** (the reindex safety net — a missed reindex fails loud, not silent) |
| `infra/storage/vector.py` | `_local_embedding` (feature hashing) | **152** |
| `infra/storage/vector.py` | `generate_embedding` (provider switch `local`/`openai` via `ATELIER_EMBEDDING_PROVIDER`) | **219–230** |
| `infra/storage/vector.py` | query/doc embedding cache `get_/put_cached_embedding`, `vector_cache_key` (cache key includes `embedder_name` → self-invalidates on name change) | in same file |
| `code_context/embedding.py` | `from ...embeddings.local import LocalEmbedder` (hard pin) | ~**13** |
| `code_context/embedding.py` | `SemanticSearchRanker._embed_query` | **163–165** |
| `git_history/embedder.py` | `_DIM = 384`; `_get_embedder()` hard-instantiates `LocalEmbedder()`; `embed_summary`/`decode_embedding`/`embedding_dim` | whole file |
| `code_context/engine.py` | `_LINEAGE_INDEX_VERSION = 1` | **155** |
| `code_context/engine.py` | `commit_chunks` schema (`embedding BLOB` @3776, `index_version` @3777) | **3769–3778** |
| `code_context/engine.py` | lineage stale-check `WHERE index_version < _LINEAGE_INDEX_VERSION` | **6408–6409** |
| `code_context/engine.py` | `_ensure_lineage_ready` / `_lineage_bootstrap_worker` / `_walk_and_summarise` (calls `embed_summary`) / `_flush_commit_batch` (insert @6512) | ~6390 / ~6437 / ~6450 / ~6505 |
| `code_context/engine.py` | **separate code-search index**: `_current_index_version` @**5245**, `_bump_index_version` @**5286**, `engine_state 'index_version'` | distinct from lineage |

## The TWO index-version mechanisms (the draft conflated these — important)

1. **Commit-lineage vectors** are invalidated by **bumping the `_LINEAGE_INDEX_VERSION`
   constant** (engine.py:155). The bootstrap worker already re-walks rows whose
   `index_version < _LINEAGE_INDEX_VERSION`.
2. **Symbol / code-search query+symbol vectors** live in the
   `playbook_embedding_cache`, keyed by `embedder.name`. Giving the new
   embedder a distinct `.name` (e.g. `ollama:nomic-embed-text`) makes old
   `local:hashing` entries cache-miss → recompute. The code-search `index_version`
   in `engine_state` (bumped via `_bump_index_version`) governs the symbol index
   cache, separate from the embedding vectors.

⇒ **W1 must do both:** bump `_LINEAGE_INDEX_VERSION` **and** ensure the new
embedder reports a new `.name`. The cosine guard at `vector.py:125` is the net
that catches any vector that slipped through at the wrong dim.

## Orchestrator verification addendum (2026-05-29) — RESOLVED facts the explore draft left open

Independently confirmed by reading the code + re-fetching primary sources:

1. **Ranker constructor** `SemanticSearchRanker.__init__` is at **83–94** (not
   89–104). Body: `self.embedder = embedder or LocalEmbedder()` (~line 93), and
   the param is typed **`embedder: LocalEmbedder | NullEmbedder | None = None`**.
   ⇒ **W1 must WIDEN this annotation** to the `Embedder` protocol / include
   `OllamaEmbedder`, or `make typecheck` fails. (The draft missed this.)
2. **The engine does NOT pass an embedder.** `engine.py:565` builds the ranker as
   `SemanticSearchRanker(self.repo_root, store_root=default_store_root())` → it
   relies on the **default** `LocalEmbedder()`. The draft listed this as "verify
   this"; it is now resolved. ⇒ W1 has **two embedder construction sites** to
   switch: (a) the ranker default (or pass `embedder=` at engine.py:565), and
   (b) the `git_history/embedder.py` `_get_embedder()` singleton.
3. **Cache self-invalidation is real.** `get_cached_embedding(..., embedder_name=)`
   (vector.py:80) and `put_cached_embedding(..., embedder_name=)` (vector.py:102)
   both key on `embedder_name`; callers prepend `self.embedder.name`. A new
   `.name` (`ollama:<model>`) ⇒ old `local:hashing` entries miss → recompute. ✅
4. **External facts re-verified on primary cards:** `nomic-embed-text` = 768-dim,
   Apache-2.0, **prefixes REQUIRED** (card: *"the text prompt must include a task
   instruction prefix"* — `search_query:`/`search_document:`), L2 required.
   `nomic-embed-code` = Apache-2.0, query prefix `Represent this query for
   searching relevant code:`, base Qwen2.5-Coder-7B (dim **3584 inferred** from
   the 7B hidden size — not printed on the card; derive at runtime).

## Ordered change-set for W1

1. **NEW** `infra/embeddings/ollama_embedder.py` — `OllamaEmbedder(Embedder)`:
   POST `http://localhost:11434/api/embed`; model from `ATELIER_CODE_EMBED_MODEL`
   (default `nomic-embed-text`); apply **required prefixes** (`search_query:` /
   `search_document:`; code model uses `Represent this query for searching
   relevant code: `) and **L2-normalize**; `.name = f"ollama:{model}"`,
   `.dim` from the model (768 default / 3584 for code); raise `OllamaUnavailable`
   on failure. Reuse the `ollama_client.py` connection pattern.
2. **EDIT** `infra/embeddings/factory.py` — add a **code-path embedder accessor**
   (do NOT change the memory-path `make_embedder()` priority): Ollama reachable
   → `OllamaEmbedder`; else `LocalEmbedder` (hashing) offline fallback.
3. **EDIT** `code_context/embedding.py:13,163` — replace the hard `LocalEmbedder`
   default in `SemanticSearchRanker` with the shared code-embedder accessor
   (the class already accepts an `embedder` param — wire the default through it).
4. **EDIT** `git_history/embedder.py` — route `_get_embedder()` through the same
   accessor; make `_DIM` dynamic from the embedder; keep struct.pack BLOB format.
5. **EDIT** `code_context/engine.py:155` — bump `_LINEAGE_INDEX_VERSION` (1→2);
   optionally persist the embed `model`/`dim` in `engine_state` so a model change
   is self-detecting.
6. **REINDEX** — see plan below.
7. **TESTS + microbench** — see GATE-EMB in `02-execution-plan.md`.

## Reindex plan

- **`commit_chunks`** (lineage): bumping `_LINEAGE_INDEX_VERSION` marks rows
  stale; the bootstrap worker rebuilds in background. For a clean wipe in tests:
  `DELETE FROM commit_chunks;` then reset `engine_state` key
  `commit_lineage_watermark`.
- **`playbook_embedding_cache`** (symbol/query vectors): no manual wipe needed
  — the new `embedder.name` causes cache misses → recompute. (Optional: prune old
  rows to reclaim space.)
- **Env vars (new, code-path only — keep separate from the memory path's
  `ATELIER_EMBEDDING_*`):** `ATELIER_CODE_EMBED_MODEL` (default `nomic-embed-text`),
  and derive dim from the model rather than a hand-set var to avoid drift.
- **Trigger:** first `_ensure_lineage_ready()` / `_ensure_indexed()` after the
  version bump rebuilds; commit search is briefly empty (~seconds) during rebuild
  (acceptable; opt-in feature).

## Risks / gotchas (verified subset)

1. **Dim mismatch is caught** at `vector.py:125` (raises) — good; but it means a
   half-reindexed store throws on query. Ensure the version bump + name change
   land together so the store is consistent.
2. **Prefixes + L2 are mandatory** for nomic (see R1 memo) — omitting them
   silently degrades recall. Implement in `OllamaEmbedder`, not at call sites.
3. **Memory-path isolation:** do NOT merge the code embedder into
   `make_embedder()`; verify `OPENAI_API_KEY`-set still gives the memory path
   OpenAI (1536), independent of the code path.
4. **Fail-open lineage worker** swallows exceptions (engine.py ~6446) — add a
   `logger.exception(...)` so a bad embed/Ollama-down is observable, not silent.
5. **Offline safety:** Ollama-unreachable must fall back to hashing, never crash
   (covered by GATE-EMB).
6. **License gate (commercial wedge):** default to Apache-2.0 nomic models; Qodo
   (RAIL-M) / Jina (CC-BY-NC) need review before shipping (see R1 memo).

## Testing checklist (for W1 + GATE-EMB)
- `OllamaEmbedder` produces N-dim L2-normalized vectors with correct prefixes.
- Query vec dim == stored commit/symbol vec dim (no `cosine_similarity` raise).
- New `embedder.name` → old cache entries ignored; recompute on miss.
- Bumping `_LINEAGE_INDEX_VERSION` triggers rebuild.
- Memory path unaffected with `OPENAI_API_KEY` set.
- Ollama down → graceful hashing fallback, no crash.
