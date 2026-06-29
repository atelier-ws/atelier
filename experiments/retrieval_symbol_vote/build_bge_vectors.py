"""Build BGE-Code-v1 symbol_vectors for the bench repos (GPU, one shared model).

Semantic search reads the index-time per-symbol vector store; the only enable is
a configured embedder (ATELIER_CODE_EMBEDDER=bge). This script triggers exactly
the index-time embedding path (engine._build_symbol_embeddings) on the EXISTING
symbols of each prebuilt bench DB -- it never reparses source, only adds the
missing `bge:BAAI/bge-code-v1` rows (N5-stamped). Idempotent: repos already
stamped with bge are skipped per-symbol by existing_stamped_ids.

GPU is the bottleneck, so repos run SEQUENTIALLY sharing ONE loaded model (a
parallel-process build would reload the 1.5B model per worker and contend on the
single GPU). Run:

    ATELIER_CODE_EMBEDDER=bge uv run --no-sync python \
        experiments/retrieval_symbol_vote/build_bge_vectors.py [--only sphinx,flask]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

os.environ.setdefault("ATELIER_CODE_EMBEDDER", "bge")
os.environ.setdefault("ATELIER_EMBED_BATCH_SIZE", "96")

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.embeddings.bge import BgeEmbedder

BENCH = "benchmarks/codebench/data/bench_pairs_multi.json"
WANT_NAME = "bge:BAAI/bge-code-v1"
WANT_DIM = 1536


def _vec_provenance(db: str) -> tuple[str, int, int]:
    """(embedder_name, dim, count) of the dominant symbol_vectors stamp, or ('', 0, 0)."""
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = c.execute(
            "SELECT embedder_name, embedding_dim, COUNT(*) FROM symbol_vectors GROUP BY 1,2 ORDER BY 3 DESC"
        ).fetchall()
        c.close()
        return (rows[0][0], int(rows[0][1]), int(rows[0][2])) if rows else ("", 0, 0)
    except sqlite3.OperationalError:
        return ("", 0, 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma substrings; build only matching repo prefixes")
    ap.add_argument("--model", default="BAAI/bge-code-v1", help="HF model id or local path (e.g. a finetuned dir)")
    args = ap.parse_args()
    only = [s for s in args.only.split(",") if s]
    global WANT_NAME
    WANT_NAME = f"bge:{args.model}"  # N5 stamp must match the embedder used to build

    repos = json.load(open(BENCH))["repos"]
    targets = []
    for prefix, meta in sorted(repos.items()):
        db = meta.get("db")
        ws = meta.get("ws")
        if not db or not ws or not os.path.isfile(db) or not os.path.isdir(ws):
            continue
        if only and not any(s in prefix for s in only):
            continue
        name, dim, n = _vec_provenance(db)
        done = name == WANT_NAME and dim == WANT_DIM
        targets.append((prefix, ws, db, name, dim, n, done))

    print("[build] plan:", file=sys.stderr)
    for prefix, ws, db, name, dim, n, done in targets:
        tag = "OK (skip)" if done else "BUILD"
        print(f"  {prefix:28s} cur={name or '(none)'} dim={dim} n={n}  -> {tag}", file=sys.stderr)
    todo = [t for t in targets if not t[6]]
    if not todo:
        print("[build] all targets already bge-stamped; nothing to do.", file=sys.stderr)
        return 0

    print(f"[build] loading shared {WANT_NAME} on GPU ...", file=sys.stderr)
    t0 = time.perf_counter()
    shared = BgeEmbedder(args.model)
    shared.embed(["warmup"])  # force model load now
    print(f"[build] model ready in {time.perf_counter() - t0:.1f}s (dim={shared.dim})", file=sys.stderr, flush=True)

    for prefix, ws, db, _name, _dim, _n, _done in todo:
        t1 = time.perf_counter()
        eng = CodeContextEngine(Path(ws), db_path=Path(db), autosync_enabled=False)
        eng._semantic_ranker.embedder = shared  # share the one loaded model across repos
        eng._ann_vectors_cache = None
        # Build through the engine's OWN scoped connection. A separate _connect()
        # collides on the shared attached vectors.sqlite (db_path.parent/vectors.sqlite
        # -> /tmp/vectors.sqlite for every bench db) whose journal_mode=WAL flip needs
        # the write lock -> "database is locked". _reuse_connection attaches once and
        # commits+closes on exit. (symbol_vectors itself lives in the MAIN db.)
        with eng._reuse_connection():
            conn = eng._scoped_conn_tls.conn
            eng._init_schema(conn)
            row = conn.execute("SELECT value FROM engine_state WHERE key = 'index_version'").fetchone()
            iv = int(row["value"]) if row is not None else 0
            eng._build_symbol_embeddings(conn, iv)
        name, dim, n = _vec_provenance(db)
        print(
            f"[build] {prefix:28s} -> {name} dim={dim} n={n}  ({time.perf_counter() - t1:.1f}s)",
            file=sys.stderr,
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
