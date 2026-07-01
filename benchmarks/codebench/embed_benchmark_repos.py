#!/usr/bin/env python3
"""Embed benchmark repo symbols with BGE directly (no engine private API).

Run with system python3 (has torch + sentence_transformers):
    python3 benchmarks/codebench/embed_benchmark_repos.py
"""

from __future__ import annotations

import json
import sqlite3
import struct
import time
from pathlib import Path

GOLD_FILES = [
    "benchmarks/codebench/data/bench_pairs_def_gold.json",
    "benchmarks/codebench/data/bench_pairs_content_gold.json",
    "benchmarks/codebench/data/bench_pairs_semantic_gold.json",
]

MAX_CHARS = 4000

# Model tiers — selected at runtime by _init_model() based on free VRAM.
# (min_free_gb, hf_model_name, embedder_name_in_db, vector_dim)
_MODEL_TIERS = [
    (3.5, "BAAI/bge-code-v1", "bge:BAAI/bge-code-v1", 1536),
    (1.0, "Salesforce/SFR-Embedding-Code-400M_R", "hf:Salesforce/SFR-Embedding-Code-400M_R", 1024),
]

# Resolved at first call to _init_model()
_MODEL_NAME: str = ""
_EMBEDDER_NAME: str = ""
_EMBED_DIM: int = 0
_BATCH_SIZE: int = 0
_model = None


def _init_model() -> None:
    """Detect free VRAM, pick model tier + batch size, load model once."""
    global _MODEL_NAME, _EMBEDDER_NAME, _EMBED_DIM, _BATCH_SIZE, _model
    if _model is not None:
        return

    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    free_gb = 0.0
    if device == "cuda":
        free_bytes, _ = torch.cuda.mem_get_info()
        free_gb = free_bytes / 1024**3

    # Pick model tier
    chosen = _MODEL_TIERS[-1]  # smallest fallback
    for min_gb, *rest in _MODEL_TIERS:
        if free_gb >= min_gb or device == "cpu":
            chosen = (min_gb, *rest)
            break
    _, _MODEL_NAME, _EMBEDDER_NAME, _EMBED_DIM = chosen

    # Batch size based on free VRAM after model load (estimate: model ~dim/512 GB)
    # Thresholds are conservative for long texts (MAX_CHARS=4000 → 1k+ tokens/sample).
    # Activation memory scales with batch×seq_len, so cap well below naive VRAM limits.
    if device == "cpu":
        _BATCH_SIZE = 4
    elif free_gb >= 20:
        _BATCH_SIZE = 128
    elif free_gb >= 12:
        _BATCH_SIZE = 32
    elif free_gb >= 8:
        _BATCH_SIZE = 16
    elif free_gb >= 5:
        _BATCH_SIZE = 8
    elif free_gb >= 3:
        _BATCH_SIZE = 4
    else:
        _BATCH_SIZE = 2

    print(
        f"  device={device}  free_vram={free_gb:.1f}GB  model={_MODEL_NAME}  dim={_EMBED_DIM}  batch={_BATCH_SIZE}",
        flush=True,
    )
    _model = SentenceTransformer(_MODEL_NAME, device=device)
    if device == "cuda":
        _model = _model.half()


def _get_model():
    _init_model()
    return _model


def _ensure_vectors_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS symbol_vectors (
            repo_id        TEXT NOT NULL,
            symbol_id      TEXT NOT NULL,
            content_hash   TEXT NOT NULL,
            embedder_name  TEXT NOT NULL,
            embedding_dim  INTEGER NOT NULL,
            index_version  INTEGER NOT NULL DEFAULT 1,
            vector_blob    BLOB NOT NULL,
            PRIMARY KEY (symbol_id, embedder_name, embedding_dim)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_symbol_vectors_provenance
            ON symbol_vectors(repo_id, embedder_name, embedding_dim, index_version)
    """)
    conn.commit()


def _has_bge_vectors(db_path: str) -> int:
    """Return count of existing BGE vectors (0 = need to embed)."""
    conn = sqlite3.connect(db_path)
    try:
        has_tbl = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='symbol_vectors'").fetchone()
        if not has_tbl:
            return 0
        return conn.execute(
            "SELECT COUNT(*) FROM symbol_vectors WHERE embedder_name = ?",
            (_EMBEDDER_NAME,),
        ).fetchone()[0]
    finally:
        conn.close()


def embed_repo(prefix: str, meta: dict) -> None:
    db_path = meta.get("db", "")
    ws_path = meta.get("ws", "")
    if not db_path or not ws_path:
        print(f"  SKIP {prefix}: no db/ws", flush=True)
        return
    if not Path(db_path).exists():
        print(f"  SKIP {prefix}: db not found", flush=True)
        return

    # Need model info to know which embedder_name to check — init first.
    _init_model()
    existing = _has_bge_vectors(db_path)
    if existing > 0:
        print(f"  {prefix}: {existing:,} existing {_EMBEDDER_NAME} vectors (checking for gaps…)", flush=True)

    print(f"  EMBED {prefix} ...", flush=True)
    t0 = time.perf_counter()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_vectors_table(conn)

    repo_id = conn.execute("SELECT DISTINCT repo_id FROM symbols LIMIT 1").fetchone()
    if not repo_id:
        print(f"  SKIP {prefix}: no symbols", flush=True)
        conn.close()
        return
    repo_id = repo_id[0]

    iv_row = conn.execute("SELECT value FROM engine_state WHERE key = 'index_version'").fetchone()
    index_version = int(iv_row[0]) if iv_row else 1

    # Already-embedded symbol_ids to skip
    done_ids: set[str] = {
        r[0]
        for r in conn.execute(
            "SELECT symbol_id FROM symbol_vectors WHERE embedder_name = ? AND embedding_dim = ?",
            (_EMBEDDER_NAME, _EMBED_DIM),
        ).fetchall()
    }

    rows = conn.execute(
        "SELECT symbol_id, content_hash, file_path, start_byte, end_byte FROM symbols WHERE repo_id = ?",
        (repo_id,),
    ).fetchall()
    pending = [r for r in rows if r["symbol_id"] not in done_ids]
    print(f"    {len(pending):,} symbols to embed", flush=True)

    if not pending:
        conn.close()
        return

    model = _get_model()
    ws = Path(ws_path)

    def _read_slice(file_path: str, start: int, end: int) -> str:
        try:
            p = ws / file_path
            data = p.read_bytes()
            return data[start:end].decode("utf-8", errors="replace")[:MAX_CHARS]
        except Exception:
            return ""

    # Bucket by approximate text length → similar-length seqs per batch → minimal padding waste
    pending.sort(key=lambda r: (r["end_byte"] or 0) - (r["start_byte"] or 0))
    import queue
    import threading

    PREFETCH = 32  # batches buffered ahead
    TOKENS_PER_BATCH = _BATCH_SIZE * 128  # token budget: scales with detected tier
    CHARS_PER_TOKEN = 4  # rough chars→tokens conversion
    q: queue.Queue = queue.Queue(maxsize=PREFETCH)

    def _producer():
        i = 0
        while i < len(pending):
            sym_len = max(1, (pending[i]["end_byte"] or 0) - (pending[i]["start_byte"] or 0))
            est_tokens = max(1, sym_len // CHARS_PER_TOKEN)
            bs = max(4, min(512, TOKENS_PER_BATCH // est_tokens))
            chunk = pending[i : i + bs]
            q.put((chunk, [_read_slice(r["file_path"], r["start_byte"] or 0, r["end_byte"] or 0) for r in chunk]))
            i += bs
        q.put(None)  # sentinel

    t = threading.Thread(target=_producer, daemon=True)
    t.start()
    inserted = 0
    while True:
        item = q.get()
        if item is None:
            break
        batch, texts = item
        vecs = model.encode(texts, batch_size=len(batch), normalize_embeddings=True, show_progress_bar=False)
        rows_to_insert = [
            (
                repo_id,
                r["symbol_id"],
                r["content_hash"],
                _EMBEDDER_NAME,
                _EMBED_DIM,
                index_version,
                struct.pack(f"{_EMBED_DIM}f", *v.tolist()),
            )
            for r, v in zip(batch, vecs, strict=False)
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO symbol_vectors "
            "(repo_id, symbol_id, content_hash, embedder_name, embedding_dim, index_version, vector_blob) "
            "VALUES (?,?,?,?,?,?,?)",
            rows_to_insert,
        )
        conn.commit()
        inserted += len(batch)
        elapsed = time.perf_counter() - t0
        rate = inserted / elapsed
        eta = (len(pending) - inserted) / rate if rate else 0
        print(f"    {inserted:,}/{len(pending):,}  {rate:.0f}/s  eta={eta:.0f}s", flush=True)

    conn.close()
    print(f"  DONE  {prefix}: {inserted:,} vectors in {time.perf_counter() - t0:.0f}s", flush=True)


def main() -> None:
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

    print(f"Found {len(all_repos)} repos", flush=True)
    for prefix, meta in sorted(all_repos.items()):
        embed_repo(prefix, meta)
    print("All done.", flush=True)


if __name__ == "__main__":
    main()
