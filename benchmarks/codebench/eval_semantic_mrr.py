"""Semantic retrieval eval: BGE-Code-v1 (or any SentenceTransformer) explore-MRR.

Evaluates MRR/hit@1/hit@3 for semantic (BGE embedding) search over the same
golden query pairs as the lexical/zoekt channels (``bench_pairs_def_gold.json``).

Two backends, tried in order per repo:
  1. Pre-built per-repo corpus embeddings at
     ``benchmarks/embedding/data/multi_repo/emb_bge_<slug>.npy`` +
     ``corpus_<slug>.jsonl`` (legacy path from ``bench_multi_repo.py``).
  2. The engine's own ``symbol_vectors`` table in the per-repo SQLite DB
     (provisioned by ``scripts/_provision_repos.py`` and indexed via
     ``atelier code index``).  This is the primary path: the golden repos in
     ``bench_pairs_def_gold.json`` all carry BGE vectors in their DBs.

Emits one JSON line: {mrr, hit1, hit3, n, latency_ms, by_repo, skipped}.

Env knobs:
  EVAL_EMB_MODEL   SentenceTransformer id (default BAAI/bge-code-v1)
  EVAL_EMB_DEVICE  cuda|cpu (default: auto)
  EVAL_EMB_DATA    dir with emb_<tag>_<repo>.npy + corpus_<repo>.jsonl
  EVAL_EMB_TAG     embedding tag in the npy filename (default: bge)
  EVAL_PAIRS       mined (query, gold-file) pairs json (default benchmarks/codebench/data/bench_pairs_def_gold.json)

Requires sentence-transformers + torch + numpy (NOT in the project venv; use the
benchmark env, e.g. system python3 with `pip install -r ../embedding/requirements_hf.txt`).
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

INSTRUCT = "<instruct>Given a natural language query, retrieve relevant code.\n<query>"

# ── Constants (matching the engine's vector stamp) ───────────────────────
WANT_EMBEDDER_NAME = "bge:BAAI/bge-code-v1"
WANT_DIM = 1536


# ── Helpers ────────────────────────────────────────────────────────────────


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def _pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int((p / 100.0) * (len(s) - 1)))]


def _cuda() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _mrr(d):
    return round(d["rr"] / max(d["n"], 1), 4)


def _agg() -> dict:
    return {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}


def _add(d: dict, rank: int | None) -> None:
    d["n"] += 1
    if rank:
        d["rr"] += 1.0 / rank
        d["h1"] += int(rank == 1)
        d["h3"] += int(rank <= 3)


def _rank_true(files: list[str], trues: list[str]) -> int | None:
    tn = [_norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(_norm(f).endswith(t) for t in tn):
            return i
    return None


# ── File-based corpus loading (legacy .npy + .jsonl) ──────────────────────


def file_from_entry(entry: dict) -> str:
    """Repo-relative file for a corpus symbol. The text embeds a ``Path: <file>``
    line, which is correct for every repo (some ids are relative, e.g. scikit's
    ``.spin.cmds`` -> mis-derived ``/spin/cmds.py``)."""
    for line in entry["text"].split("\n"):
        if line.startswith("Path:"):
            p = line[len("Path:") :].strip()
            return p if p.endswith(".py") else p + ".py"
    return entry["id"].split("::", 1)[0].replace(".", "/") + ".py"


def _load_corpus_files(data_dir: Path, tag: str, slug: str) -> tuple[np.ndarray | None, list[str]]:
    """Try loading the pre-built .npy + .jsonl corpus for *slug*.

    Returns (matrix, file_list) or (None, []) on miss.
    """
    emb_path = data_dir / f"emb_{tag}_{slug}.npy"
    corpus_path = data_dir / f"corpus_{slug}.jsonl"
    if not emb_path.exists() or not corpus_path.exists():
        return None, []
    matrix = np.load(emb_path)
    files = [file_from_entry(json.loads(line)) for line in open(corpus_path)]
    return matrix, files


# ── DB-based vector loading (engine's symbol_vectors table) ────────────────


def _vec_dbs_for(main_db: str) -> list[str]:
    """Candidate DB files that may hold this repo's BGE vectors.

    The main per-repo DB carries vectors for most repos.  The shared
    vectors.sqlite sidecar is also checked for repos provisioned via
    the engine path.
    """
    cands = [main_db, str(Path(main_db).parent / "vectors.sqlite")]
    seen: set[str] = set()
    return [c for c in cands if os.path.isfile(c) and not (c in seen or seen.add(c))]


def _load_db_vectors(db_path: str, embedder_name: str = WANT_EMBEDDER_NAME, dim: int = WANT_DIM):
    """Load symbol vectors from an engine SQLite DB.

    Returns (symbol_ids, matrix[N, dim] float32, file_path_for[symbol_id]).
    Returns empty arrays / {} when the table or vectors are missing.
    """
    # read file_of mapping from the main DB (innocent until proven guilty)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        file_of: dict[str, str] = {r[0]: r[1] for r in conn.execute("SELECT symbol_id, file_path FROM symbols")}
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError, Exception):
        return [], np.zeros((0, WANT_DIM), np.float32), {}

    ids: list[str] = []
    vecs: list[list[float]] = []
    for vdb in _vec_dbs_for(db_path):
        try:
            c = sqlite3.connect(f"file:{vdb}?mode=ro", uri=True)
            rows = c.execute(
                "SELECT symbol_id, vector_blob FROM symbol_vectors WHERE embedder_name=? AND embedding_dim=?",
                (embedder_name, dim),
            ).fetchall()
            c.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            continue
        if rows:
            for sid, blob in rows:
                if sid not in file_of:
                    continue
                if not isinstance(blob, (bytes, bytearray, memoryview)):
                    continue
                blob = bytes(blob)
                if len(blob) != dim * 4:
                    continue
                ids.append(sid)
                vecs.append(np.frombuffer(blob, dtype=np.float32))
            break  # first db that has matching rows wins
    matrix = np.vstack(vecs).astype(np.float32) if vecs else np.zeros((0, dim), np.float32)
    return ids, matrix, file_of


# ── Semantic file ranking ──────────────────────────────────────────────────


def _semantic_files(
    qv: np.ndarray, ids: list[str], matrix: np.ndarray, file_of: dict[str, str], k: int = 10
) -> list[str]:
    """Rank files by best symbol cosine similarity.  Deduplicates to *k* files."""
    if matrix.shape[0] == 0:
        return []
    scores = matrix @ qv
    order = np.argsort(-scores)
    out: list[str] = []
    seen: set[str] = set()
    for i in order:
        f = _norm(file_of.get(ids[int(i)], ""))
        if f and f not in seen:
            seen.add(f)
            out.append(f)
        if len(out) >= k:
            break
    return out


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="Semantic retrieval eval (BGE-code MRR)")
    ap.add_argument("--full", action="store_true", help="Run all available query pairs (no cap).")
    ap.add_argument("--sample", type=int, default=0, help="Total queries to sample across repos (0 = all).")
    ap.add_argument("--repo", default="", metavar="SUBSTR", help="Only repos whose prefix contains SUBSTR.")
    ap.add_argument(
        "--pairs",
        default=os.environ.get("EVAL_PAIRS", "benchmarks/codebench/data/bench_pairs_def_gold.json"),
        help="Mined (query, gold-file) pairs JSON.",
    )
    ap.add_argument("--model", default=os.environ.get("EVAL_EMB_MODEL", "BAAI/bge-code-v1"), help="HF model id")
    args = ap.parse_args()

    data_dir = Path(os.environ.get("EVAL_EMB_DATA", "benchmarks/embedding/data/multi_repo"))
    tag = os.environ.get("EVAL_EMB_TAG", "bge")
    device = os.environ.get("EVAL_EMB_DEVICE") or ("cuda" if _cuda() else "cpu")
    embedder_name = f"bge:{args.model}"
    print(f"[sem-eval] loading {args.model} on {device}  pairs={args.pairs}", file=sys.stderr, flush=True)

    # --pairs may be a comma-separated list of golds; embed/rank each query once
    # (the union) and score against every gold so all channels share one query set.
    _gold_paths = [p.strip() for p in args.pairs.split(",") if p.strip()]
    _golds = []  # (gold_kind, pairs, true_map)
    repos_meta: dict[str, dict] = {}
    for _gp in _gold_paths:
        _d = json.load(open(_gp))
        if not repos_meta:
            repos_meta = _d.get("repos", {})
        _golds.append((_d.get("gold_kind", "definition"), _d["pairs"], _d["true_map"]))
    pairs = [row for _k, _p, _tm in _golds for row in _p]

    # ── Model ──
    model = SentenceTransformer(args.model, trust_remote_code=True, device=device)
    model.eval()
    model.encode(["warmup"], normalize_embeddings=True)

    def embed(texts):
        return np.array(model.encode(texts, batch_size=8, normalize_embeddings=True), dtype=np.float32)

    # ── Collect unique queries per repo (respecting --sample / --repo) ──
    uq: dict[str, list[str]] = {}
    for q, _tid, prefix in pairs:
        if args.repo and args.repo not in prefix:
            continue
        uq.setdefault(prefix, [])
        if q not in uq[prefix]:
            uq[prefix].append(q)
    if args.sample:
        n_repos = max(len(uq), 1)
        per_repo = max(1, args.sample // n_repos)
        uq = {p: sorted(qs)[:per_repo] for p, qs in uq.items()}
    runset = {p: set(qs) for p, qs in uq.items()}

    # Legacy PREFIX_TO_SLUG mapping for the .npy + .jsonl path
    PREFIX_TO_SLUG = {
        "django__django": "django",
        "astropy__astropy": "astropy",
        "pydata__xarray": "xarray",
        "pytest-dev__pytest": "pytest",
        "scikit-learn__scikit-learn": "scikit-learn",
    }

    # ── Per-repo eval ──
    _gold_aggs = {kind: _agg() for kind, _p, _tm in _golds}
    _gold_by_repo: dict[str, dict] = {kind: {} for kind, _p, _tm in _golds}
    latencies: list[float] = []
    skipped: list[str] = []

    for prefix in sorted(uq):
        if args.repo and args.repo not in prefix:
            continue

        queries = uq[prefix]
        repo_pairs = [(q, tid) for q, tid, p in pairs if p == prefix and q in runset.get(prefix, set())]
        if not repo_pairs:
            continue

        # -- Try backend 1: pre-built .npy + .jsonl files (legacy) --
        slug = PREFIX_TO_SLUG.get(prefix)
        matrix: np.ndarray | None = None
        files: list[str] = []
        source_label: str = ""
        if slug:
            matrix, files = _load_corpus_files(data_dir, tag, slug)
            if matrix is not None:
                source_label = "npy"

        # -- Try backend 2: SQLite symbol_vectors from engine DB --
        db_path: str | None = None
        v_ids: list[str] = []
        v_file_of: dict[str, str] = {}
        if matrix is None:
            meta = repos_meta.get(prefix, {})
            db_path = meta.get("db") or meta.get("db_path")
            if db_path and os.path.isfile(db_path):
                v_ids, matrix, v_file_of = _load_db_vectors(db_path, embedder_name)
                if matrix is not None and matrix.shape[0] > 0:
                    source_label = "db"

        if matrix is None or matrix.shape[0] == 0:
            skipped.append(prefix)
            print(
                f"[sem-eval] {prefix:28s} no vectors (tried npy + db)  -> skip",
                file=sys.stderr,
                flush=True,
            )
            continue

        print(
            f"[sem-eval] {prefix:28s} {len(queries):4d} q  vecs={matrix.shape[0]:6d}  {source_label}",
            file=sys.stderr,
            flush=True,
        )

        # -- Embed queries (one batch per repo) --
        t0 = time.perf_counter()
        q_texts = [f"{INSTRUCT}{q}" for q in queries]
        qmat = embed(q_texts)
        per_query_time = (time.perf_counter() - t0) / max(len(queries), 1) * 1000.0

        # -- Rank per query --
        qrank: dict[str, list[str]] = {}
        for qi, q in enumerate(queries):
            if source_label == "db":
                ranked = _semantic_files(qmat[qi], v_ids, matrix, v_file_of, k=10)
            else:
                # npy path: matrix rows align with files, dedup to file
                qv = qmat[qi]
                order = np.argsort(-(matrix @ qv))
                ranked, seen = [], set()
                for i in order:
                    f = files[int(i)]
                    if f not in seen:
                        seen.add(f)
                        ranked.append(f)
                    if len(ranked) >= 10:
                        break
            qrank[q] = ranked

        # -- Score each gold against this repo's rankings --
        for _kind, _gp, _gtm in _golds:
            _br = _gold_by_repo[_kind].setdefault(prefix, _agg())
            for q, tid, p in _gp:
                if p != prefix or q not in runset.get(prefix, set()):
                    continue
                trues = _gtm.get(tid)
                if not trues:
                    continue
                rank = _rank_true(qrank.get(q, []), trues)
                _add(_gold_aggs[_kind], rank)
                _add(_br, rank)

        # Per-query latency estimate (one embed call with n queries)
        latencies.extend([per_query_time] * len(queries))

    # ── Output ──
    def _gold_out(gagg, gby):
        return {
            "mrr": _mrr(gagg),
            "hit1": round(gagg["h1"] / max(gagg["n"], 1), 4),
            "hit3": round(gagg["h3"] / max(gagg["n"], 1), 4),
            "n": gagg["n"],
            "by_repo": {p: {"mrr": _mrr(d), "n": d["n"]} for p, d in sorted(gby.items())},
        }

    _gold_scores = {kind: _gold_out(_gold_aggs[kind], _gold_by_repo[kind]) for kind, _p, _tm in _golds}
    out = {
        **_gold_scores[_golds[0][0]],
        "latency_ms": {
            "mean": round(sum(latencies) / max(len(latencies), 1), 1),
            "p95": round(_pct(latencies, 95), 1),
            "max": round(max(latencies), 1) if latencies else 0.0,
        },
        "skipped": skipped,
        "golds": _gold_scores,
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
