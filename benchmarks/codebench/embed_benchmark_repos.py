#!/usr/bin/env python3
"""Embed benchmark repo symbols with BGE using system python3 (has torch/sentence_transformers).

Run with system python3, NOT uv run:
    python3 benchmarks/codebench/embed_benchmark_repos.py

Reads all gold files, finds repos missing BGE symbol_vectors, and populates them
by loading each repo's CodeContextEngine with ATELIER_CODE_EMBEDDER=bge.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# Use project src directly (system python3 has torch; uv venv does not)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

os.environ.setdefault("ATELIER_CODE_EMBEDDER", "bge")

GOLD_FILES = [
    "benchmarks/codebench/data/bench_pairs_def_gold.json",
    "benchmarks/codebench/data/bench_pairs_content_gold.json",
    "benchmarks/codebench/data/bench_pairs_semantic_gold.json",
]


def _has_bge_vectors(db_path: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        has_tbl = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='symbol_vectors'").fetchone()
        if not has_tbl:
            return False
        n = conn.execute("SELECT COUNT(*) FROM symbol_vectors WHERE embedder_name LIKE 'bge%'").fetchone()[0]
        return n > 0
    finally:
        conn.close()


def embed_repo(prefix: str, meta: dict) -> None:
    db_path = meta.get("db", "")
    ws_path = meta.get("ws", "")
    if not db_path or not ws_path:
        print(f"  SKIP {prefix}: no db/ws", flush=True)
        return
    if not Path(db_path).exists():
        print(f"  SKIP {prefix}: db not found ({db_path})", flush=True)
        return
    if not Path(ws_path).exists():
        print(f"  SKIP {prefix}: ws not found ({ws_path})", flush=True)
        return
    if _has_bge_vectors(db_path):
        conn = sqlite3.connect(db_path)
        n = conn.execute("SELECT COUNT(*) FROM symbol_vectors WHERE embedder_name LIKE 'bge%'").fetchone()[0]
        conn.close()
        print(f"  SKIP {prefix}: already has {n:,} BGE vectors", flush=True)
        return

    print(f"  EMBED {prefix} ...", flush=True)
    t0 = time.perf_counter()

    from atelier.core.capabilities.code_context.engine import CodeContextEngine

    engine = CodeContextEngine(
        Path(ws_path),
        db_path=Path(db_path),
        autosync_enabled=False,
    )

    # Trigger embedding: open the DB, ensure schema, call _build_symbol_embeddings.
    # We read the stored index_version so we don't invalidate the existing index.
    conn = engine._open_connection()
    try:
        engine._ensure_schema(conn)
        iv_row = conn.execute("SELECT value FROM engine_state WHERE key = 'index_version'").fetchone()
        index_version = int(iv_row[0]) if iv_row else 1
        engine._build_symbol_embeddings(conn, index_version)
        conn.commit()
    finally:
        conn.close()

    elapsed = time.perf_counter() - t0
    # Verify
    conn2 = sqlite3.connect(db_path)
    n = conn2.execute("SELECT COUNT(*) FROM symbol_vectors WHERE embedder_name LIKE 'bge%'").fetchone()[0]
    conn2.close()
    print(f"  DONE  {prefix}: {n:,} BGE vectors in {elapsed:.0f}s", flush=True)


def main() -> None:
    # Collect all repos across gold files (dedup by prefix)
    all_repos: dict[str, dict] = {}
    for gf in GOLD_FILES:
        try:
            data = json.loads(Path(gf).read_text())
        except FileNotFoundError:
            print(f"WARNING: gold file not found: {gf}")
            continue
        for prefix, meta in data.get("repos", {}).items():
            if prefix not in all_repos:
                all_repos[prefix] = meta

    print(f"Found {len(all_repos)} repos across {len(GOLD_FILES)} gold files", flush=True)
    for prefix, meta in sorted(all_repos.items()):
        embed_repo(prefix, meta)
    print("All done.", flush=True)


if __name__ == "__main__":
    main()
