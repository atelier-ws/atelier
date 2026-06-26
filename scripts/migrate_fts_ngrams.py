#!/usr/bin/env python3
"""Rebuild symbol_fts with n-gram tokens for all benchmark databases.

Usage:
    uv run python scripts/migrate_fts_ngrams.py

This is a fast migration -- no tree-sitter re-parse needed.  It reads the
existing `symbols` rows, rebuilds `symbol_fts` with the augmented name column
(original symbol name + stripped-join bigrams + full compound), then
re-populates.  Typical time: <5 s per repo.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

# Inline the same logic as _ngram_tokens / _identifier_terms so this script
# has zero import dependencies on the atelier package.
_FTS_TERM_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _ngram_tokens(name: str) -> list[str]:
    pieces: list[str] = []
    for raw in _FTS_TERM_RE.findall(name):
        for camel in _CAMEL_RE.split(raw):
            for piece in camel.split("_"):
                p = piece.strip().lower()
                if p:
                    pieces.append(p)
    if len(pieces) < 2:
        return []
    out: list[str] = []
    for i in range(len(pieces) - 1):
        out.append(pieces[i] + pieces[i + 1])
    if len(pieces) >= 3:
        out.append("".join(pieces))
    return out


def migrate(db_path: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row

    # Read existing symbols + their current FTS source text.
    rows = conn.execute(
        "SELECT s.symbol_id, s.symbol_name, s.qualified_name, s.kind,"
        " s.signature, s.file_path, f.source"
        " FROM symbols s"
        " LEFT JOIN symbol_fts f ON f.symbol_id = s.symbol_id"
    ).fetchall()

    # Clear and re-populate symbol_fts.
    conn.execute("DELETE FROM symbol_fts")
    n_augmented = 0
    fts_rows: list[tuple[str, str, str, str, str, str]] = []
    for r in rows:
        ngrams = _ngram_tokens(r["symbol_name"] or "")
        if ngrams:
            fts_name = r["symbol_name"] + " " + " ".join(ngrams)
            n_augmented += 1
        else:
            fts_name = r["symbol_name"] or ""
        fts_rows.append(
            (
                r["symbol_id"],
                fts_name,
                r["qualified_name"] or "",
                r["signature"] or "",
                r["file_path"] or "",
                r["source"] or "",
            )
        )

    conn.executemany(
        "INSERT INTO symbol_fts(symbol_id, name, qualified_name, signature, file_path, source)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        fts_rows,
    )
    conn.commit()
    conn.close()
    return {"total": len(rows), "augmented": n_augmented}


def main() -> None:
    pairs_file = Path("benchmarks/codebench/data/bench_pairs_multi.json")
    if not pairs_file.exists():
        print(f"Pairs file not found: {pairs_file}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(pairs_file.read_text())
    repos = data.get("repos", {})
    if not repos:
        print("No repos found in pairs file.", file=sys.stderr)
        sys.exit(1)

    for prefix, info in sorted(repos.items()):
        db_path = info.get("db", "")
        if not db_path or not Path(db_path).exists():
            print(f"  SKIP {prefix}: db not found ({db_path})")
            continue
        t0 = time.time()
        stats = migrate(db_path)
        elapsed = time.time() - t0
        print(f"  {prefix}: {stats['total']} symbols, {stats['augmented']} augmented  ({elapsed:.1f}s)  [{db_path}]")


if __name__ == "__main__":
    main()
