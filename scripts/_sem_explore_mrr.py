"""Scratch: semantic-only explore-MRR using the PRE-BUILT BGE corpus embeddings.

Reuses benchmarks/embedding/data/multi_repo/emb_bge_<repo>.npy (corpus symbol
vectors, HF BAAI/bge-code-v1, normalized) + corpus_<repo>.jsonl (id->file).
Embeds the EXPLORE benchmark's queries with the SAME HF pipeline + instruction
prefix, ranks files by cosine, and scores rank-of-gold-file like the explore
harness.  Apples-to-apples vs lexical (0.3975) and lexical+zoekt (0.4775).
"""

import json
import sys
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

DATA = Path("benchmarks/embedding/data/multi_repo")
# explore-benchmark prefix -> embedding-benchmark repo slug
PREFIX_TO_SLUG = {
    "django__django": "django",
    "astropy__astropy": "astropy",
    "pydata__xarray": "xarray",
    "pytest-dev__pytest": "pytest",
    "scikit-learn__scikit-learn": "scikit-learn",
}


def id_to_file(cid: str) -> str:
    # Fallback only: "django.template.defaultfilters::wordwrap#part1" -> file.
    mod = cid.split("::", 1)[0]
    return mod.replace(".", "/") + ".py"


def file_from_entry(o: dict) -> str:
    # The corpus text embeds a repo-relative "Path: <file-no-ext>" line, which is
    # correct for every repo (the dotted id is relative for some, e.g. scikit's
    # ".spin.cmds" -> mis-derived "/spin/cmds.py"). Prefer the Path line.
    for line in o["text"].split("\n"):
        if line.startswith("Path:"):
            p = line[len("Path:") :].strip()
            return p if p.endswith(".py") else p + ".py"
    return id_to_file(o["id"])


def norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def main() -> int:
    data = json.load(open("/tmp/bench_pairs_multi.json"))
    pairs, true_map = data["pairs"], data["true_map"]
    print("loading BAAI/bge-code-v1 (cached)...", file=sys.stderr, flush=True)
    model = SentenceTransformer("BAAI/bge-code-v1", trust_remote_code=True, device="cpu")
    model.eval()

    def embed(texts):
        return np.array(model.encode(texts, batch_size=8, normalize_embeddings=True), dtype=np.float32)

    agg = {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}
    by_repo = {}
    for prefix, slug in PREFIX_TO_SLUG.items():
        emb_path = DATA / f"emb_bge_{slug}.npy"
        corpus_path = DATA / f"corpus_{slug}.jsonl"
        if not emb_path.exists() or not corpus_path.exists():
            print(f"skip {prefix}: missing artifacts", file=sys.stderr)
            continue
        corpus_vecs = np.load(emb_path)
        files = [file_from_entry(json.loads(line)) for line in open(corpus_path)]
        # explore queries for this repo (unique, deterministic) + their gold
        repo_pairs = [(q, tid) for q, tid, p in pairs if p == prefix]
        uniq_q = sorted({q for q, _ in repo_pairs})
        q_texts = [f"<instruct>Given a natural language query, retrieve relevant code.\n<query>{q}" for q in uniq_q]
        print(f"{prefix}: embedding {len(uniq_q)} queries vs {len(files)} corpus syms", file=sys.stderr, flush=True)
        qvecs = embed(q_texts)
        qrank = {}
        for q, qv in zip(uniq_q, qvecs):
            order = np.argsort(-(corpus_vecs @ qv))
            ranked_files, seen = [], set()
            for i in order:
                f = files[i]
                if f not in seen:
                    seen.add(f)
                    ranked_files.append(f)
                if len(ranked_files) >= 10:
                    break
            qrank[q] = ranked_files
        br = by_repo.setdefault(prefix, {"rr": 0.0, "h1": 0, "h3": 0, "n": 0})
        for q, tid in repo_pairs:
            trues = [norm(t) for t in (true_map.get(tid) or [])]
            if not trues:
                continue
            rank = None
            for idx, f in enumerate(qrank.get(q, []), 1):
                if any(norm(f).endswith(t) or t.endswith(norm(f)) for t in trues):
                    rank = idx
                    break
            for d in (agg, br):
                d["n"] += 1
                if rank:
                    d["rr"] += 1.0 / rank
                    d["h1"] += int(rank == 1)
                    d["h3"] += int(rank <= 3)
        print(f"  {prefix} mrr={br['rr'] / max(br['n'], 1):.4f} n={br['n']}", file=sys.stderr, flush=True)

    def mrr(d):
        return round(d["rr"] / max(d["n"], 1), 4)

    out = {
        "mrr": mrr(agg),
        "hit1": round(agg["h1"] / max(agg["n"], 1), 4),
        "hit3": round(agg["h3"] / max(agg["n"], 1), 4),
        "n": agg["n"],
        "by_repo": {p: {"mrr": mrr(d), "n": d["n"]} for p, d in sorted(by_repo.items())},
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
