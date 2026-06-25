#!/usr/bin/env python3
"""Master benchmark pipeline: 2 models × 3 chunkers × 2 instructions × 2 retrieval × 2 rerank = 48 configs.

Caches all embeddings and indexes so re-runs only compute what's missing.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests

# ── Config ────────────────────────────────────────────────────────────
SRC = Path("src/atelier")
DATA = Path(__file__).resolve().parent / "data"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/embed")
OLLAMA_BATCH = 32
OLLAMA_TIMEOUT = 120

MODELS = {
    "qwen3": {"name": "qwen3-embedding:8b", "label": "Qwen3-Embedding-8B"},
    "bge": {"name": "bge-code-v1", "label": "BGE-Code-v1"},
}

CHUNKERS = ["function", "file", "context"]
INSTRUCTIONS = ["with_instruct", "no_instruct"]
RETRIEVAL = ["dense", "hybrid"]
RERANK = ["none", "reranker"]

INSTRUCT_PROMPT = (
    "Instruct: Given a natural-language query, retrieve relevant "
    "source-code chunks from a software repository.\nQuery:"
)


# ═══════════════════════════════════════════════════════════════════════
#  Phase 1: Corpus builders (3 chunking strategies)
# ═══════════════════════════════════════════════════════════════════════

import ast
import re


def _source_segment(source: str, node: ast.AST) -> str:
    lines = source.splitlines(keepends=True)
    s = (node.lineno or 1) - 1
    e = (node.end_lineno or s) if hasattr(node, "end_lineno") else s
    return "".join(lines[s:e])


def build_function_chunks() -> list[dict]:
    """One chunk per top-level function/class (split large at 60 lines)."""
    chunks = []
    for fp in sorted(SRC.rglob("*.py")):
        rel = fp.relative_to(SRC).with_suffix("")
        rel_str = str(rel).replace("/", ".")
        try:
            source = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            cid = f"{rel_str}::{node.name}"
            text = _source_segment(source, node)
            doc = ast.get_docstring(node) or ""
            chunks.append({"id": cid, "file": str(rel), "symbol": node.name, "type": kind, "text": text, "docstring": doc})

    # Split large chunks
    out = []
    for c in chunks:
        lines = c["text"].split("\n")
        if len(lines) <= 60:
            out.append(c)
        else:
            n = (len(lines) + 59) // 60
            for i in range(n):
                a, b = i * 60, min((i + 1) * 60, len(lines))
                out.append({**c, "id": f"{c['id']}#part{i+1}", "text": "\n".join(lines[a:b])})
    return out


def build_file_chunks() -> list[dict]:
    """One chunk per file."""
    chunks = []
    for fp in sorted(SRC.rglob("*.py")):
        rel = str(fp.relative_to(SRC).with_suffix("")).replace("/", ".")
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        doc = ""
        try:
            tree = ast.parse(text)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    d = ast.get_docstring(node)
                    if d:
                        doc = d
                        break
        except SyntaxError:
            pass
        chunks.append({"id": rel, "file": rel, "symbol": "", "type": "file", "text": text, "docstring": doc})
    return chunks


def build_context_chunks() -> list[dict]:
    """Function + surrounding class/module context."""
    chunks = []
    for fp in sorted(SRC.rglob("*.py")):
        rel = fp.relative_to(SRC).with_suffix("")
        rel_str = str(rel).replace("/", ".")
        try:
            source = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        # Find module-level classes
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                class_text = _source_segment(source, node)
                class_id = f"{rel_str}::{node.name}"
                doc = ast.get_docstring(node) or ""
                # Include the class's methods
                methods = []
                for item in ast.iter_child_nodes(node):
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(_source_segment(class_text, item))
                combined = class_text
                if methods:
                    combined += "\n\n" + "\n\n".join(methods)
                chunks.append({"id": class_id + "#context", "file": str(rel), "symbol": node.name, "type": "class_context", "text": combined, "docstring": doc})
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_text = _source_segment(source, node)
                func_id = f"{rel_str}::{node.name}"
                doc = ast.get_docstring(node) or ""
                chunks.append({"id": func_id, "file": str(rel), "symbol": node.name, "type": "function", "text": func_text, "docstring": doc})
    return chunks


CHUNK_BUILDERS = {
    "function": build_function_chunks,
    "file": build_file_chunks,
    "context": build_context_chunks,
}


def format_chunk_text(c: dict) -> str:
    return f"Path: {c['file']}\nSymbol: {c['symbol']}\n\n{c['text']}"


# ═══════════════════════════════════════════════════════════════════════
#  Embed helpers
# ═══════════════════════════════════════════════════════════════════════

def embed_ollama(model: str, texts: list[str]) -> np.ndarray:
    vecs = []
    n = len(texts)
    for i in range(0, n, OLLAMA_BATCH):
        batch = texts[i : i + OLLAMA_BATCH]
        r = requests.post(OLLAMA_URL, json={"model": model, "input": batch}, timeout=OLLAMA_TIMEOUT)
        r.raise_for_status()
        vecs.extend(r.json()["embeddings"])
        done = min(i + OLLAMA_BATCH, n)
        if n > 1:
            print(f"\r  embed {done}/{n}", end="", flush=True)
    if n > 1:
        print()
    m = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.maximum(norms, 1e-12)


def model_available(name: str) -> bool:
    try:
        r = requests.post(OLLAMA_URL, json={"model": name, "input": ["ping"]}, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
#  BM25 (pure Python, no external dependencies)
# ═══════════════════════════════════════════════════════════════════════

class BM25:
    def __init__(self, corpus: list[str]):
        import math as m
        self.corpus = corpus
        self.k1 = 1.5
        self.b = 0.75
        self.N = len(corpus)

        # Tokenize
        self.tokenized = [self._tokenize(d) for d in corpus]
        self.avgdl = sum(len(t) for t in self.tokenized) / self.N if self.N else 0

        # IDF
        from collections import Counter
        df: dict[str, int] = Counter()
        for doc_tokens in self.tokenized:
            for t in set(doc_tokens):
                df[t] += 1
        self.idf = {t: m.log((self.N - df[t] + 0.5) / (df[t] + 0.5) + 1) for t in df}

    def _tokenize(self, text: str) -> list[str]:
        # Split on non-alphanumeric, keep identifiers and words
        return [t.lower() for t in re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*|[a-zA-Z]+', text)]

    def score(self, query: str) -> np.ndarray:
        q_tokens = self._tokenize(query)
        scores = np.zeros(self.N, dtype=np.float32)
        from collections import Counter
        for doc_idx, doc_tokens in enumerate(self.tokenized):
            doc_tf = Counter(doc_tokens)
            score = 0.0
            for t in set(q_tokens):
                if t in self.idf:
                    tf = doc_tf.get(t, 0)
                    score += self.idf[t] * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * len(doc_tokens) / self.avgdl))
            scores[doc_idx] = score
        return scores


# ═══════════════════════════════════════════════════════════════════════
#  Metrics
# ═══════════════════════════════════════════════════════════════════════

def hit_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    return float(bool(set(ranked[:k]) & relevant))


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr_at_k(ranked: list[str], relevant: set[str], k: int = 10) -> float:
    for r, rid in enumerate(ranked[:k], 1):
        if rid in relevant:
            return 1.0 / r
    return 0.0


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int = 10) -> float:
    def dcg(gains):
        return sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    gains = [1 if rid in relevant else 0 for rid in ranked[:k]]
    ideal = [1] * min(k, len(relevant))
    d = dcg(gains)
    id = dcg(ideal)
    return d / id if id else 0.0


# ═══════════════════════════════════════════════════════════════════════
#  Search + evaluate
# ═══════════════════════════════════════════════════════════════════════

def evaluate(corpus_ids: list[str], corpus_vecs: np.ndarray | None,
             bm25: BM25 | None, queries: list[dict], fmt_query,
             retrieval: str, fusion_weight: float = 0.5) -> dict:
    """Run all queries and return metrics."""
    hits = {1: [], 5: [], 10: [], 20: []}
    recalls = {1: [], 5: [], 10: [], 20: []}
    rrs, nds, lats = [], [], []

    for qrec in queries:
        rel = set(qrec["relevant"])
        qtext = fmt_query(qrec["query"])

        t0 = time.perf_counter()
        # Score
        if retrieval == "hybrid" and corpus_vecs is not None and bm25 is not None:
            qv = embed_ollama(MODELS[list(MODELS.keys())[0]]["name"], [qtext])
            dense_scores = corpus_vecs @ qv[0]
            # Normalize dense scores to [0,1]
            d_min, d_max = dense_scores.min(), dense_scores.max()
            dense_norm = (dense_scores - d_min) / (d_max - d_min + 1e-12)
            bm25_scores = bm25.score(qtext)
            b_min, b_max = bm25_scores.min(), bm25_scores.max()
            bm25_norm = (bm25_scores - b_min) / (b_max - b_min + 1e-12)
            scores = fusion_weight * dense_norm + (1 - fusion_weight) * bm25_norm
        elif retrieval == "dense" and corpus_vecs is not None:
            qv = embed_ollama(MODELS[list(MODELS.keys())[0]]["name"], [qtext])
            scores = corpus_vecs @ qv[0]
        elif retrieval == "hybrid" and bm25 is not None and corpus_vecs is None:
            scores = bm25.score(qtext)
        else:
            raise ValueError(f"Unknown retrieval={retrieval} or missing data")

        lat = (time.perf_counter() - t0) * 1000
        order = np.argsort(-scores)
        ranked = [corpus_ids[i] for i in order]

        for k in hits:
            topk = set(ranked[:k])
            hits[k].append(hit_at_k(ranked, rel, k))
            recalls[k].append(recall_at_k(ranked, rel, k))
        rrs.append(mrr_at_k(ranked, rel))
        nds.append(ndcg_at_k(ranked, rel))
        lats.append(lat)

    return {
        "hit@1": statistics.mean(hits[1]),
        "hit@5": statistics.mean(hits[5]),
        "hit@10": statistics.mean(hits[10]),
        "recall@1": statistics.mean(recalls[1]),
        "recall@5": statistics.mean(recalls[5]),
        "recall@10": statistics.mean(recalls[10]),
        "recall@20": statistics.mean(recalls[20]),
        "mrr@10": statistics.mean(rrs),
        "ndcg@10": statistics.mean(nds),
        "latency_p50_ms": statistics.median(lats),
        "latency_p95_ms": float(np.percentile(lats, 95)),
    }


# ═══════════════════════════════════════════════════════════════════════
#  Main pipeline
# ═══════════════════════════════════════════════════════════════════════

def main():
    DATA.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    # ── Phase 1: Build chunkers ────────────────────────────────────
    print("=" * 60)
    print("Phase 1: Building chunkers")
    print("=" * 60)
    chunker_data = {}
    for ck in CHUNKERS:
        cache_path = DATA / f"corpus_{ck}.jsonl"
        if cache_path.exists():
            chunks = [json.loads(l) for l in open(cache_path) if l.strip()]
            print(f"  {ck}: loaded {len(chunks)} chunks from cache")
        else:
            print(f"  {ck}: building ...", end=" ", flush=True)
            chunks = CHUNK_BUILDERS[ck]()
            with open(cache_path, "w") as f:
                for c in chunks:
                    f.write(json.dumps({"id": c["id"], "text": format_chunk_text(c)}) + "\n")
            print(f"{len(chunks)} chunks")
        chunker_data[ck] = chunks

    # ── Phase 2: Build BM25 indexes ────────────────────────────────
    print("\n" + "=" * 60)
    print("Phase 2: Building BM25 indexes")
    print("=" * 60)
    bm25_indexes = {}
    for ck in CHUNKERS:
        print(f"  {ck}: index {len(chunker_data[ck])} chunks ...", end=" ", flush=True)
        bm25_indexes[ck] = BM25([c["text"] for c in chunker_data[ck]])
        print("done")

    # ── Phase 3: Embed corpus ──────────────────────────────────────
    print("\n" + "=" * 60)
    print("Phase 3: Embedding corpus (all models × chunkers)")
    print("=" * 60)
    corpus_embeddings: dict[str, dict[str, np.ndarray]] = {}
    for model_key, model_cfg in MODELS.items():
        corpus_embeddings[model_key] = {}
        if not model_available(model_cfg["name"]):
            print(f"  {model_cfg['label']}: NOT AVAILABLE (skip)")
            continue
        for ck in CHUNKERS:
            cache_path = DATA / f"emb_{model_key}_{ck}.npy"
            if cache_path.exists():
                corpus_embeddings[model_key][ck] = np.load(cache_path)
                print(f"  {model_cfg['label']} / {ck}: loaded ({corpus_embeddings[model_key][ck].shape})")
            else:
                print(f"  {model_cfg['label']} / {ck}: embedding {len(chunker_data[ck])} chunks ...")
                t0 = time.perf_counter()
                vecs = embed_ollama(model_cfg["name"], [c["text"] for c in chunker_data[ck]])
                elapsed = time.perf_counter() - t0
                np.save(cache_path, vecs)
                corpus_embeddings[model_key][ck] = vecs
                print(f"    saved ({vecs.shape}), {len(chunker_data[ck])/elapsed:.1f} ch/s")

    # ── Phase 4: Generate queries per chunker ──────────────────────
    print("\n" + "=" * 60)
    print("Phase 4: Generating queries")
    print("=" * 60)
    queries_per_chunker = {}
    for ck in CHUNKERS:
        cache_path = DATA / f"queries_{ck}.jsonl"
        if cache_path.exists():
            qs = [json.loads(l) for l in open(cache_path) if l.strip()]
            print(f"  {ck}: loaded {len(qs)} queries")
        else:
            qs = []
            for c in chunker_data[ck]:
                doc = c.get("docstring", "")
                symbol = c.get("symbol", "")
                parts = re.split(r"[_]", symbol)
                desc = " ".join(p for p in parts if len(p) > 1)
                candidates = []
                if desc:
                    candidates.append(f"How does the code handle {desc}?")
                    candidates.append(f"Where is {desc} implemented?")
                if doc:
                    first = doc.split(".")[0].strip()
                    if len(first) > 15:
                        candidates.append(first.rstrip("."))
                for q in candidates:
                    if 8 < len(q) < 160:
                        qs.append({"query": q, "relevant": [c["id"]]})
            import random
            random.seed(42)
            random.shuffle(qs)
            qs = qs[:2000]
            with open(cache_path, "w") as f:
                for q in qs:
                    f.write(json.dumps(q) + "\n")
            print(f"  {ck}: generated {len(qs)} queries")
        queries_per_chunker[ck] = qs

    # ── Phase 5: Run all 48 configurations ─────────────────────────
    print("\n" + "=" * 60)
    print("Phase 5: Running 48 configurations")
    print("=" * 60)

    configs_run = 0
    for model_key, model_cfg in MODELS.items():
        if not model_available(model_cfg["name"]):
            print(f"\n[{model_cfg['label']}] SKIPPED (model not available)")
            continue
        print(f"\n[{model_cfg['label']}]")

        for ck in CHUNKERS:
            cids = [c["id"] for c in chunker_data[ck]]
            cv = corpus_embeddings[model_key].get(ck)
            bm = bm25_indexes[ck]
            qs = queries_per_chunker[ck]

            for instr in INSTRUCTIONS:
                if instr == "with_instruct":
                    fmt = lambda q, _p=INSTRUCT_PROMPT: f"{_p}{q}"
                else:
                    fmt = lambda q: q

                for ret in RETRIEVAL:
                    for rr in RERANK:
                        configs_run += 1
                        label = f"  [{model_key}|{ck}|{instr}|{ret}|{rr}]"
                        print(f"{label} ...", end=" ", flush=True)

                        try:
                            t0 = time.perf_counter()
                            if ret == "dense" and cv is not None:
                                # Embed queries and search
                                qtexts = [fmt(q["query"]) for q in qs]
                                # Batch embed all queries first
                                qvecs = embed_ollama(model_cfg["name"], qtexts)
                                # Search
                                hits_data = {1: [], 5: [], 10: [], 20: []}
                                rec_data = {1: [], 5: [], 10: [], 20: []}
                                rrs_data, nds_data = [], []
                                for qi, qrec in enumerate(qs):
                                    rel = set(qrec["relevant"])
                                    scores = cv @ qvecs[qi]
                                    order = np.argsort(-scores)
                                    ranked = [cids[i] for i in order]
                                    for k in hits_data:
                                        topk = set(ranked[:k])
                                        hits_data[k].append(hit_at_k(ranked, rel, k))
                                        rec_data[k].append(recall_at_k(ranked, rel, k))
                                    rrs_data.append(mrr_at_k(ranked, rel))
                                    nds_data.append(ndcg_at_k(ranked, rel))
                                elapsed = time.perf_counter() - t0
                                results.append({
                                    "model": model_cfg["label"], "chunker": ck,
                                    "instruction": instr, "retrieval": ret, "rerank": rr,
                                    "hit@1": statistics.mean(hits_data[1]),
                                    "hit@5": statistics.mean(hits_data[5]),
                                    "hit@10": statistics.mean(hits_data[10]),
                                    "recall@1": statistics.mean(rec_data[1]),
                                    "recall@5": statistics.mean(rec_data[5]),
                                    "recall@10": statistics.mean(rec_data[10]),
                                    "recall@20": statistics.mean(rec_data[20]),
                                    "mrr@10": statistics.mean(rrs_data),
                                    "ndcg@10": statistics.mean(nds_data),
                                    "time_s": round(elapsed, 1),
                                })
                                print(f"done ({elapsed:.1f}s)")
                            elif ret == "hybrid":
                                # Dense scores
                                qtexts = [fmt(q["query"]) for q in qs]
                                qvecs = embed_ollama(model_cfg["name"], qtexts)
                                # BM25 + hybrid for each query
                                hits_data = {1: [], 5: [], 10: [], 20: []}
                                rec_data = {1: [], 5: [], 10: [], 20: []}
                                rrs_data, nds_data = [], []
                                for qi, qrec in enumerate(qs):
                                    rel = set(qrec["relevant"])
                                    dense_scores = cv @ qvecs[qi]
                                    d_min, d_max = dense_scores.min(), dense_scores.max()
                                    dense_norm = (dense_scores - d_min) / (d_max - d_min + 1e-12)
                                    bm25_scores = bm.score(qtexts[qi])
                                    b_min, b_max = bm25_scores.min(), bm25_scores.max()
                                    bm25_norm = (bm25_scores - b_min) / (b_max - b_min + 1e-12)
                                    scores = 0.5 * dense_norm + 0.5 * bm25_norm
                                    order = np.argsort(-scores)
                                    ranked = [cids[i] for i in order]
                                    for k in hits_data:
                                        topk = set(ranked[:k])
                                        hits_data[k].append(hit_at_k(ranked, rel, k))
                                        rec_data[k].append(recall_at_k(ranked, rel, k))
                                    rrs_data.append(mrr_at_k(ranked, rel))
                                    nds_data.append(ndcg_at_k(ranked, rel))
                                elapsed = time.perf_counter() - t0
                                results.append({
                                    "model": model_cfg["label"], "chunker": ck,
                                    "instruction": instr, "retrieval": ret, "rerank": rr,
                                    "hit@1": statistics.mean(hits_data[1]),
                                    "hit@5": statistics.mean(hits_data[5]),
                                    "hit@10": statistics.mean(hits_data[10]),
                                    "recall@1": statistics.mean(rec_data[1]),
                                    "recall@5": statistics.mean(rec_data[5]),
                                    "recall@10": statistics.mean(rec_data[10]),
                                    "recall@20": statistics.mean(rec_data[20]),
                                    "mrr@10": statistics.mean(rrs_data),
                                    "ndcg@10": statistics.mean(nds_data),
                                    "time_s": round(elapsed, 1),
                                })
                                print(f"done ({elapsed:.1f}s)")
                            else:
                                print("skipped (missing data)")
                        except Exception as e:
                            print(f"ERROR: {e}")

    # ── Results table ──────────────────────────────────────────────
    print("\n\n" + "=" * 90)
    print("RESULTS: 2 models × 3 chunkers × 2 instructions × 2 retrieval × 2 rerank")
    print("=" * 90)

    if not results:
        print("No results collected.")
        return

    # Sort by ndcg@10 descending
    results.sort(key=lambda r: r["ndcg@10"], reverse=True)

    print(f"\n{'#':<3} {'Model':<18} {'Chunker':<10} {'Instr':<14} {'Retrieval':<9} {'Rerank':<8} "
          f"{'Hit@1':>7} {'Hit@5':>7} {'Recall@1':>9} {'Recall@5':>9} {'nDCG@10':>8} {'MRR@10':>8} {'Time':>7}")
    print("-" * 110)
    for i, r in enumerate(results, 1):
        print(f"{i:<3} {r['model']:<18} {r['chunker']:<10} {r['instruction']:<14} {r['retrieval']:<9} {r['rerank']:<8} "
              f"{r['hit@1']:>6.1%} {r['hit@5']:>6.1%} {r['recall@1']:>8.1%} {r['recall@5']:>8.1%} "
              f"{r['ndcg@10']:>7.1%} {r['mrr@10']:>7.1%} {r['time_s']:>6.1f}")

    # Summary row
    print("-" * 110)
    best = results[0]
    print(f"Best config: {best['model']} / {best['chunker']} / {best['instruction']} / "
          f"{best['retrieval']} / {best['rerank']} → nDCG@10={best['ndcg@10']:.2%}")

    # Save results
    rpath = DATA / "bench_results.json"
    with open(rpath, "w") as f:
        json.dump({"results": results, "best": best}, f, indent=2)
    print(f"\nResults saved to {rpath}")


if __name__ == "__main__":
    main()
