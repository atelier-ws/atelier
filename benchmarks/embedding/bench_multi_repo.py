"""BGE-Code-v1 benchmark across 6 SWE-bench repos, one repo at a time.

Usage:
  python bench_multi_repo.py <repo-name>
  python bench_multi_repo.py all     # run all 6 sequentially

Saves results to multi_repo/results_<repo>.json (per-repo, never overwritten).
"""
from __future__ import annotations

import ast
import json
import math
import pathlib
import random
import re
import statistics
import sys
import time

import numpy as np
import requests as req
import torch
from sentence_transformers import SentenceTransformer

ALL_REPOS = ["django", "pytest", "astropy", "sympy", "scikit-learn", "xarray"]
REPO_DIR = pathlib.Path("/tmp/swe_repos")
OUT_DIR = pathlib.Path("/home/pankaj/Projects/leanchain/atelier/benchmarks/embedding/data/multi_repo")
OLLAMA_URL = "http://localhost:11434/api/embed"
MIN_CHUNK_CHARS = 40
random.seed(42)
OUT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    print(msg, flush=True)


# ── Chunking ─────────────────────────────────────────────────────────
def _source_segment(source: str, node: ast.AST) -> str:
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1 if hasattr(node, "lineno") else 0
    end = (node.end_lineno if hasattr(node, "end_lineno") and node.end_lineno else start)
    return "".join(lines[start:end])


def extract_chunks(filepath: str, src_root: pathlib.Path) -> list[dict]:
    path = pathlib.Path(filepath)
    rel = path.relative_to(src_root).with_suffix("")
    rel_str = str(rel).replace("/", ".")
    chunks = []
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return chunks
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return chunks
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else \
                   "class" if isinstance(node, ast.ClassDef) else "function"
            chunk_id = f"{rel_str}::{node.name}"
            text = _source_segment(source, node)
            doc = ast.get_docstring(node) or ""
            chunks.append({
                "id": chunk_id, "file": str(rel), "symbol": node.name,
                "type": kind, "text": text, "docstring": doc,
            })
    return chunks


def split_long_chunks(chunks: list[dict], max_lines: int = 60) -> list[dict]:
    out = []
    for c in chunks:
        lines = c["text"].split("\n")
        if len(lines) <= max_lines:
            out.append(c)
        else:
            n = (len(lines) + max_lines - 1) // max_lines
            for i in range(n):
                a, b = i * max_lines, min((i + 1) * max_lines, len(lines))
                out.append({**c, "id": f"{c['id']}#part{i+1}", "text": "\n".join(lines[a:b])})
    return out


def make_queries(chunk: dict) -> list[dict]:
    results = []
    symbol = chunk["symbol"]
    docstring = chunk["docstring"]
    ctype = chunk["type"]
    parts = re.split(r"[_]", symbol)
    desc = " ".join(p for p in parts if len(p) > 1)
    if desc:
        if ctype == "class":
            results.append(f"Which class implements {desc}?")
            results.append(f"Find the {desc} class definition")
        else:
            results.append(f"How does the code handle {desc}?")
            results.append(f"Where is {desc} implemented?")
            if parts and parts[0] in ("get", "set", "is", "has", "find", "load", "save", "create", "delete", "update"):
                results.append(f"Find the function that {parts[0]}s {' '.join(parts[1:])}")
    if docstring:
        first = docstring.split(".")[0].strip()
        if len(first) > 15:
            if first.lower().startswith("return "):
                results.append(f"What does the function return when {' '.join(first.split()[1:])}?")
            elif first.lower().startswith("raise"):
                results.append(f"When is {first} raised?")
            elif not first.endswith("?"):
                q = first.rstrip(".")
                if len(q) > 120:
                    q = q[:117] + "..."
                results.append(q)
    seen = set()
    final = []
    for q in results:
        key = q.lower().strip()
        if key not in seen and 8 < len(q) < 160:
            seen.add(key)
            final.append({"query": q, "relevant": [chunk["id"]]})
    return final


def build_repo_corpus(repo_name: str) -> tuple[list[dict], list[dict]]:
    corpus_path = OUT_DIR / f"corpus_{repo_name}.jsonl"
    queries_path = OUT_DIR / f"queries_{repo_name}.jsonl"
    if corpus_path.exists():
        log(f"  {repo_name}: corpus exists, loading...")
        chunks = [json.loads(l) for l in open(corpus_path) if l.strip()]
        queries = [json.loads(l) for l in open(queries_path) if l.strip()] if queries_path.exists() else []
        return chunks, queries

    repo_path = REPO_DIR / repo_name
    if not repo_path.exists():
        log(f"  SKIP: {repo_name} not found")
        return [], []

    exclude_dirs = {"tests", "test", "docs", "examples", "benchmarks", "build", "dist", ".git", "__pycache__", "env", "venv", ".tox", ".eggs", "*.egg-info", "node_modules"}
    py_files = sorted(repo_path.rglob("*.py"))
    filtered = []
    for f in py_files:
        rel = f.relative_to(repo_path)
        parts = rel.parts
        if any(p in exclude_dirs for p in parts):
            continue
        if "test" in parts:
            continue
        if len(parts) == 1 and parts[0] == "__init__.py":
            continue
        filtered.append(f)
    if not filtered:
        filtered = [f for f in py_files if "test" not in f.relative_to(repo_path).parts]

    all_chunks = []
    for fp in filtered:
        all_chunks.extend(extract_chunks(str(fp), repo_path))
    before = len(all_chunks)
    all_chunks = [c for c in all_chunks if len(c["text"]) > MIN_CHUNK_CHARS]
    all_chunks = split_long_chunks(all_chunks)
    log(f"  {repo_name}: {len(all_chunks)} chunks ({before - len(all_chunks)} tiny filtered) from {len(filtered)} files")
    if not all_chunks:
        return [], []

    with open(corpus_path, "w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps({
                "id": c["id"],
                "text": f"Path: {c['file']}\nSymbol: {c['symbol']}\n\n{c['text']}",
            }) + "\n")

    all_queries = []
    for c in all_chunks:
        all_queries.extend(make_queries(c))
    random.shuffle(all_queries)
    if len(all_queries) > 500:
        all_queries = all_queries[:500]

    with open(queries_path, "w", encoding="utf-8") as f:
        for q in all_queries:
            f.write(json.dumps(q) + "\n")
    log(f"  {repo_name}: {len(all_queries)} queries")
    return all_chunks, all_queries


# ── Embedding ────────────────────────────────────────────────────────
device = "cuda" if torch.cuda.is_available() else "cpu"
# Use FP16 to halve GPU memory
model_kwargs = {"torch_dtype": torch.float16} if device == "cuda" else {}
log(f"\n── Loading BGE-Code-v1 on {device} (FP16) ──")
t0 = time.time()
bge_model = SentenceTransformer("BAAI/bge-code-v1", trust_remote_code=True, device=device, model_kwargs=model_kwargs)
bge_model.eval()
if device == "cuda":
    bge_model.half()
log(f"  Loaded in {time.time()-t0:.1f}s")


def bge_embed(texts, batch_size=8):
    show_bar = len(texts) > 16  # only show progress bar for bulk embeddings
    return np.array(
        bge_model.encode(texts, batch_size=batch_size, show_progress_bar=show_bar, normalize_embeddings=True),
        dtype=np.float32,
    )


def qwen_embed(texts):
    r = req.post(OLLAMA_URL, json={"model": "qwen3-embedding:8b", "input": texts}, timeout=300)
    r.raise_for_status()
    return np.array(r.json()["embeddings"], dtype=np.float32)


def evaluate(corpus_vecs, embed_fn, queries, cid, use_instruction=True):
    hits = {1: [], 5: [], 10: []}
    rrs = []
    nds = []
    for q in queries:
        rel = set(q["relevant"])
        if use_instruction:
            q_text = f"<instruct>Given a natural language query, retrieve relevant code.\n<query>{q['query']}"
        else:
            q_text = q["query"]
        qv = embed_fn([q_text])
        ranked = [cid[i] for i in np.argsort(-(corpus_vecs @ qv[0]))]
        for k in hits:
            topk = set(ranked[:k])
            hits[k].append(float(bool(topk & rel)))
        for r, rid in enumerate(ranked[:10], 1):
            if rid in rel:
                rrs.append(1.0 / r)
                break
        else:
            rrs.append(0.0)
        gains = [1 if rid in rel else 0 for rid in ranked[:10]]
        ideal_len = min(10, len(rel))
        d = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
        id_ = sum(1 / math.log2(i + 2) for i in range(ideal_len))
        nds.append(d / id_ if id_ else 0.0)
    return {
        "hit@1": statistics.mean(hits[1]),
        "hit@5": statistics.mean(hits[5]),
        "hit@10": statistics.mean(hits[10]),
        "mrr@10": statistics.mean(rrs),
        "ndcg@10": statistics.mean(nds),
    }


# ── Per-repo runner ──────────────────────────────────────────────────
def run_repo(repo: str, skip_qwen: bool = False):
    result_path = OUT_DIR / f"results_{repo}.json"
    if result_path.exists():
        log(f"  {repo}: results already exist, loading...")
        return json.load(open(result_path))

    log(f"\n─── {repo} ───")
    chunks, queries = build_repo_corpus(repo)
    if not chunks or not queries:
        log("  SKIP: empty corpus/queries")
        return None

    eval_queries = queries[:200]
    cid = [c["id"] for c in chunks]
    corp_texts = [c["text"] for c in chunks]

    # BGE
    bge_path = OUT_DIR / f"emb_bge_{repo}.npy"
    if bge_path.exists():
        log("  Loading cached BGE embeddings...")
        corpus_bge = np.load(bge_path)
    else:
        # Smaller batch for large repos to avoid OOM (19k chunks = OOM at bs=4)
        bs = 2  # batch_size-2 safe for all repos on 24 GiB card
        log(f"  Embedding ({len(chunks)} chunks) with BGE (batch_size={bs})...")
        t0 = time.time()
        corpus_bge = bge_embed(corp_texts, batch_size=bs)
        log(f"    Done: {corpus_bge.shape}, {time.time()-t0:.1f}s")
        np.save(bge_path, corpus_bge)

    log(f"  Evaluating BGE on {len(eval_queries)} queries...")
    res_bge = evaluate(corpus_bge, bge_embed, eval_queries, cid, use_instruction=True)
    log(f"    BGE:  hit@1={res_bge['hit@1']:.2%}  hit@5={res_bge['hit@5']:.2%}  hit@10={res_bge['hit@10']:.2%}  "
        f"MRR={res_bge['mrr@10']:.2%}  nDCG={res_bge['ndcg@10']:.2%}")

    result = {"bge": res_bge}

    # Qwen
    if not skip_qwen:  # Qwen for all repos
        qwen_path = OUT_DIR / f"emb_qwen_{repo}.npy"
        if qwen_path.exists():
            log("  Loading cached Qwen embeddings...")
            corpus_qwen = np.load(qwen_path)
        else:
            log("  Embedding with Qwen3...")
            try:
                t0 = time.time()
                corpus_qwen = qwen_embed(corp_texts)
                log(f"    Done: {corpus_qwen.shape}, {time.time()-t0:.1f}s")
                np.save(qwen_path, corpus_qwen)
            except Exception as e:
                log(f"    Qwen failed: {e}")
                result["qwen"] = {"error": str(e)}
                json.dump(result, open(result_path, "w"), indent=2)
                return result

        log("  Evaluating Qwen...")
        try:
            res_q = evaluate(corpus_qwen, qwen_embed, eval_queries, cid, use_instruction=True)
            log(f"    Qwen: hit@1={res_q['hit@1']:.2%}  hit@5={res_q['hit@5']:.2%}  hit@10={res_q['hit@10']:.2%}  "
                f"MRR={res_q['mrr@10']:.2%}  nDCG={res_q['ndcg@10']:.2%}")
            result["qwen"] = res_q
        except Exception as e:
            log(f"    Qwen eval failed: {e}")
            result["qwen"] = {"error": str(e)}


    json.dump(result, open(result_path, "w"), indent=2)
    return result


# ── Main ─────────────────────────────────────────────────────────────
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    skip_qwen = "--skip-qwen" in sys.argv

    if "all" in args:
        repos = ALL_REPOS
    elif args:
        repos = args
    else:
        log("Usage: python bench_multi_repo.py <repo> [repos...] | all [--skip-qwen]")
        sys.exit(1)

    results = {}
    for repo in repos:
        res = run_repo(repo, skip_qwen=skip_qwen)
        if res is not None:
            results[repo] = res

    # Print combined summary
    log("\n" + "=" * 80)
    log("COMBINED BGE RESULTS")
    log("=" * 80)

    metrics = ["hit@1", "hit@5", "hit@10", "mrr@10", "ndcg@10"]
    header = f"{'Repo':14s}" + "".join(f"{m:>10s}" for m in metrics)
    log(f"\n{header}")
    log("-" * len(header))
    avgs = {m: [] for m in metrics}
    for r in repos:
        if r not in results:
            continue
        res = results[r].get("bge", {})
        if not res:
            continue
        vals = "".join(f"{res[m]:>9.1%}" for m in metrics)
        log(f"{r:14s}{vals}")
        for m in metrics:
            avgs[m].append(res[m])
    if avgs["hit@1"]:
        avg_line = "".join(f"{statistics.mean(avgs[m]):>9.1%}" for m in metrics)
        log(f"{'─── AVG ───':14s}{avg_line}")

    # Save combined summary
    combined = {}
    for r in repos:
        rp = OUT_DIR / f"results_{r}.json"
        if rp.exists():
            combined[r] = json.load(open(rp))
    json.dump(combined, open(OUT_DIR / "summary.json", "w"), indent=2, default=str)
    log(f"\nCombined summary: {OUT_DIR / 'summary.json'}")
    log("Done.")


if __name__ == "__main__":
    main()
