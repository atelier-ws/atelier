"""Semantic retrieval eval: BGE-Code-v1 (or any SentenceTransformer) explore-MRR.

Reuses the PRE-BUILT per-repo corpus embeddings under
``benchmarks/embedding/data/multi_repo/`` (``emb_bge_<repo>.npy`` +
``corpus_<repo>.jsonl``) as a symbol-embedding index, embeds the mined explore
benchmark queries with the SAME HF pipeline + instruction prefix, ranks files by
cosine, and scores rank-of-gold-file exactly like ``fitness_explore_mrr.py`` --
so the number is apples-to-apples with the lexical / +zoekt channels.

This is the semantic arm of the retrieval eval (see RETRIEVAL_EVAL.md). It is a
STANDALONE retrieval probe -- semantic is not yet fused into ``tool_explore`` --
so it answers "does the embedding model help on these queries?" before investing
in engine fusion.

Env knobs:
  EVAL_EMB_MODEL   SentenceTransformer id (default BAAI/bge-code-v1)
  EVAL_EMB_DEVICE  cuda|cpu (default: auto)
  EVAL_EMB_DATA    dir with emb_<tag>_<repo>.npy + corpus_<repo>.jsonl
  EVAL_EMB_TAG     embedding tag in the npy filename (default: bge)
  EVAL_PAIRS       mined (query, gold-file) pairs json (default /tmp/bench_pairs_multi.json)

Requires sentence-transformers + torch + numpy (NOT in the project venv; use the
benchmark env, e.g. system python3 with `pip install -r ../embedding/requirements_hf.txt`).
Emits one JSON line: {mrr, hit1, hit3, n, latency_ms, by_repo, skipped}.
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

# explore-benchmark repo prefix -> embedding-benchmark repo slug
PREFIX_TO_SLUG = {
    "django__django": "django",
    "astropy__astropy": "astropy",
    "pydata__xarray": "xarray",
    "pytest-dev__pytest": "pytest",
    "scikit-learn__scikit-learn": "scikit-learn",
}
INSTRUCT = "<instruct>Given a natural language query, retrieve relevant code.\n<query>"

DATA = Path(os.environ.get("EVAL_EMB_DATA", "benchmarks/embedding/data/multi_repo"))
TAG = os.environ.get("EVAL_EMB_TAG", "bge")
MODEL_ID = os.environ.get("EVAL_EMB_MODEL", "BAAI/bge-code-v1")
PAIRS = os.environ.get("EVAL_PAIRS", "/tmp/bench_pairs_multi.json")


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def file_from_entry(entry: dict) -> str:
    """Repo-relative file for a corpus symbol. The text embeds a ``Path: <file>``
    line, which is correct for every repo (some ids are relative, e.g. scikit's
    ``.spin.cmds`` -> mis-derived ``/spin/cmds.py``)."""
    for line in entry["text"].split("\n"):
        if line.startswith("Path:"):
            p = line[len("Path:") :].strip()
            return p if p.endswith(".py") else p + ".py"
    return entry["id"].split("::", 1)[0].replace(".", "/") + ".py"


def _pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int((p / 100.0) * (len(s) - 1)))]


def main() -> int:
    data = json.load(open(PAIRS))
    pairs, true_map = data["pairs"], data["true_map"]
    device = os.environ.get("EVAL_EMB_DEVICE") or ("cuda" if _cuda() else "cpu")
    print(f"[sem-eval] loading {MODEL_ID} on {device}", file=sys.stderr, flush=True)
    model = SentenceTransformer(MODEL_ID, trust_remote_code=True, device=device)
    model.eval()
    model.encode(["warmup"], normalize_embeddings=True)

    def embed(texts):
        return np.array(model.encode(texts, batch_size=8, normalize_embeddings=True), dtype=np.float32)

    agg = {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}
    by_repo, latencies, skipped = {}, [], []
    for prefix, slug in PREFIX_TO_SLUG.items():
        emb_path = DATA / f"emb_{TAG}_{slug}.npy"
        corpus_path = DATA / f"corpus_{slug}.jsonl"
        if not emb_path.exists() or not corpus_path.exists():
            skipped.append(prefix)
            continue
        corpus_vecs = np.load(emb_path)
        files = [file_from_entry(json.loads(line)) for line in open(corpus_path)]
        repo_pairs = [(q, tid) for q, tid, p in pairs if p == prefix]
        uniq_q = sorted({q for q, _ in repo_pairs})
        qrank = {}
        for q in uniq_q:
            t0 = time.perf_counter()
            qv = embed([INSTRUCT + q])[0]
            order = np.argsort(-(corpus_vecs @ qv))
            ranked, seen = [], set()
            for i in order:
                f = files[i]
                if f not in seen:
                    seen.add(f)
                    ranked.append(f)
                if len(ranked) >= 10:
                    break
            latencies.append((time.perf_counter() - t0) * 1000.0)
            qrank[q] = ranked
        br = by_repo.setdefault(prefix, {"rr": 0.0, "h1": 0, "h3": 0, "n": 0})
        for q, tid in repo_pairs:
            trues = [_norm(t) for t in (true_map.get(tid) or [])]
            if not trues:
                continue
            rank = None
            for idx, f in enumerate(qrank.get(q, []), 1):
                if any(_norm(f).endswith(t) or t.endswith(_norm(f)) for t in trues):
                    rank = idx
                    break
            for d in (agg, br):
                d["n"] += 1
                if rank:
                    d["rr"] += 1.0 / rank
                    d["h1"] += int(rank == 1)
                    d["h3"] += int(rank <= 3)

    def mrr(d):
        return round(d["rr"] / max(d["n"], 1), 4)

    out = {
        "mrr": mrr(agg),
        "hit1": round(agg["h1"] / max(agg["n"], 1), 4),
        "hit3": round(agg["h3"] / max(agg["n"], 1), 4),
        "n": agg["n"],
        "latency_ms": {
            "mean": round(sum(latencies) / max(len(latencies), 1), 1),
            "p95": round(_pct(latencies, 95), 1),
            "max": round(max(latencies), 1) if latencies else 0.0,
        },
        "by_repo": {p: {"mrr": mrr(d), "n": d["n"]} for p, d in sorted(by_repo.items())},
        "skipped": skipped,
    }
    print(json.dumps(out))
    return 0


def _cuda() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
