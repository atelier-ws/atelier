# Embedding & Reranker Model Decision (W0/R1)

> W0 deliverable, produced by `atelier:research`, persisted by orchestrator 2026-05-29.
> Authoritative input for W1 (EMB). Every number carries a source URL.

> **TL;DR (recommendation).** Ship a two-tier local embedding stack served via Ollama. **Default (zero-friction): `nomic-embed-text` v1.5 — 768-dim, 137M params, ~274 MB, `ollama pull nomic-embed-text`, Apache-2.0, already in the Ollama library today.** It matches OpenAI `text-embedding-3-small` and beats `ada-002` on MTEB, so reindexing CODE + COMMIT-LINEAGE to **768 dims** is a strict upgrade over today's 384-dim feature-hashing embedder with essentially no friction. **Quality upgrade (code-specialized): `nomic-ai/nomic-embed-code` (7B, Qwen2.5-Coder-7B base, Apache-2.0)** at **3584 dims**, served locally via the community Ollama port `manutic/nomic-embed-code` (or its official GGUF), reindex target **3584 dims**. Add a **`bge-reranker-v2-m3`** cross-encoder (Ollama port `qllama/bge-reranker-v2-m3`) only as an optional second-stage reranker once the neural bi-encoder is in place. Anthropic has **no first-party embeddings endpoint** as of May 2026 and points users to **Voyage AI**; `voyage-code-3` is the cloud quality ceiling for the cloud-fallback path. Two hard gotchas: nomic models **require task prefixes** (`search_query:` / `search_document:` for the text model; `Represent this query for searching relevant code:` for the code model) and **L2-normalization**; both support **Matryoshka truncation** so the index dim can be tuned down later.

## 1. Default local code-embed model — `nomic-embed-text`

| Attribute | Value | Source |
|---|---|---|
| Ollama presence (May 2026) | Yes — `:latest`, `:v1.5`, `:137m-v1.5-fp16` | ollama.com/library/nomic-embed-text |
| Pull command | `ollama pull nomic-embed-text` | ollama.com/library/nomic-embed-text |
| Embedding dimension | **768** native; Matryoshka 512/256/128/64 | HF nomic-embed-text-v1.5 |
| Params / size | 137M / ~274 MB | ollama.com/library/nomic-embed-text |
| Max context | 8192 (dynamic RoPE) | HF card |
| License | Apache-2.0 | HF card |
| Prefixes (required) | `search_query:`, `search_document:` | HF card |
| Normalization | L2 required (layer_norm before Matryoshka truncation) | HF card |

**Benchmark standing vs OpenAI.** MTEB 62.39 vs 62.26 (`text-embedding-3-small`); LoCo 85.53 vs 82.40; exceeds `ada-002`. (General-text, not code-specific.) Sources: nomic.ai/news/nomic-embed-text-v1; arXiv 2402.01613.

## 2. Code-specialized local options

| Model | Output dim | Params | VRAM | License | Local serving | Code score |
|---|---|---|---|---|---|---|
| **`nomic-ai/nomic-embed-code`** | **3584** | 7B (Qwen2.5-Coder-7B) | ~14 GB BF16; ~4.1 GB Q4_K_M | **Apache-2.0** | Ollama `manutic/nomic-embed-code`; official `nomic-embed-code-GGUF`; ST | CodeSearchNet: Py 81.7/Java 80.5/Ruby 81.8/Go 93.8/PHP 72.3/JS 77.1; "beats Voyage-Code-3 & OpenAI-3-Large" |
| **`Qodo/Qodo-Embed-1-1.5B`** | **1536** | 1.5B | ~3 GB (est) | QodoAI-Open-RAIL-M (use-restricted) | ST/Transformers; **no official Ollama/GGUF** | **CoIR 68.53–70.06**; 32K ctx; no prefix |
| `Qodo/Qodo-Embed-1-7B` | 1536 (UNVERIFIED) | 7B | ~14 GB (est) | RAIL-M | ST | **CoIR 71.5** |
| **`jinaai/jina-code-embeddings-1.5b`** | 1536 (Matryoshka) | ~2B | ~4 GB (est) | **CC-BY-NC-4.0 (non-commercial)** | ST; 0.5b has official GGUF | 0.5b = 78.41% avg (arXiv 2508.21290) |
| `jina-embeddings-v2-base-code` | 768 (UNVERIFIED) | 161M (UNVERIFIED) | <1 GB | Apache-2.0 (UNVERIFIED) | no `-code` Ollama tag confirmed | superseded |

**Notes:** `nomic-embed-code` is the standout commercially-usable (Apache-2.0) local code retriever with a ready Ollama port; query prefix `Represent this query for searching relevant code: `. `Qodo` has the best *published CoIR* among small open models but is **RAIL-M** (use-restricted). `jina-code-embeddings` is strong but **CC-BY-NC** (non-commercial). Sources: HF model cards; qodo.ai blog; PRNewswire; arXiv 2508.21290.

## 3. Local cross-encoder reranker

| Reranker | Params | Local serving | Latency | License |
|---|---|---|---|---|
| **`BAAI/bge-reranker-v2-m3`** | ~278M–0.6B | Ollama `qllama/bge-reranker-v2-m3`; ST CrossEncoder | ~130 ms/16-pair batch CPU | check BAAI license |
| `jinaai/jina-reranker-v2-base-multilingual` | 278M | GGUF (gpustack); no first-party Ollama | flash-attn 3–6× | **CC-BY-NC-4.0** |

**Worth it?** Yes, but **Phase 2** (after the bi-encoder lands and is validated). Rerank only the top 10–30 bi-encoder candidates; gate behind a candidate-count threshold. Prefer `bge-reranker-v2-m3` (clean Ollama path, lighter license footprint) over jina (CC-BY-NC). Sources: ollama.com/qllama/bge-reranker-v2-m3; HF cards; localaimaster reranking guide.

## 4. Anthropic embeddings? (cloud-fallback path)

**No first-party endpoint (May 2026).** Claude docs: *"Anthropic does not offer its own embedding model,"* recommend **Voyage AI**. Cloud ceiling **`voyage-code-3`**: 1024 default (256/512/2048 Matryoshka), 32K ctx; +13.80% avg over OpenAI-3-large on 32 code datasets; first 200M tokens free. Sources: platform.claude.com/docs/.../embeddings; blog.voyageai.com/2024/12/04/voyage-code-3.

## 5. Recommendation block

| Tier | Model | Serving | **Reindex target dim** | License |
|---|---|---|---|---|
| **Default** | `nomic-embed-text` v1.5 | `ollama pull nomic-embed-text` | **768** | Apache-2.0 |
| **Quality (code)** | `nomic-ai/nomic-embed-code` 7B | `manutic/nomic-embed-code` or GGUF Q4_K_M | **3584** | Apache-2.0 |
| **Reranker (Phase 2)** | `bge-reranker-v2-m3` | `qllama/bge-reranker-v2-m3` | n/a (scores) | check license |
| **Cloud ceiling** | `voyage-code-3` | Voyage API | 1024 | commercial API |

### Must-implement in `OllamaEmbedder`
1. **Asymmetric prefixes** — nomic-text: `search_query:` / `search_document:`; nomic-code: `Represent this query for searching relevant code: ` on queries, none on docs. Qodo: none. Jina: task instructions.
2. **L2-normalize** all vectors before cosine; for nomic Matryoshka: layer_norm → truncate → L2.
3. **Index-version bump** required on dim/model change (see X1 touch-points doc).
4. **Dim must match** across query + stored vectors; reconfigure the vector store to the chosen dim.
5. **License gate for the commercial wedge:** prefer Apache-2.0 nomic models; Qodo (RAIL-M) and Jina (CC-BY-NC) need legal review before shipping.

## UNVERIFIED
- `nomic-embed-code` exact CoIR average (CodeSearchNet verified; ">20% over Voyage on CoIR" is a secondary paraphrase).
- Qodo-7B dim; Qodo/Jina VRAM (estimated); jina-0.5b dim (896 inferred); jina-v2-base-code specifics; nomic-embed-code exact Matryoshka dim list; bge-reranker exact param count.

## Sources
ollama.com/library/nomic-embed-text · huggingface.co/nomic-ai/nomic-embed-text-v1.5 · nomic.ai/news/nomic-embed-text-v1 · arxiv.org/abs/2402.01613 · huggingface.co/nomic-ai/nomic-embed-code(-GGUF) · ollama.com/manutic/nomic-embed-code · nomic.ai/news/introducing-state-of-the-art-nomic-embed-code · huggingface.co/Qodo/Qodo-Embed-1-1.5B(-7B) · qodo.ai/blog/qodo-embed-1-code-embedding-code-retrieval · prnewswire (Qodo CoIR 70.06) · huggingface.co/jinaai/jina-code-embeddings-1.5b(/0.5b-GGUF) · arxiv.org/abs/2508.21290 · huggingface.co/BAAI/bge-reranker-v2-m3 · ollama.com/qllama/bge-reranker-v2-m3 · huggingface.co/jinaai/jina-reranker-v2-base-multilingual(/gpustack GGUF) · localaimaster.com/blog/reranking-cross-encoders-guide · platform.claude.com/docs/en/docs/build-with-claude/embeddings · github.com/anthropics/claude-cookbooks (VoyageAI) · blog.voyageai.com/2024/12/04/voyage-code-3
