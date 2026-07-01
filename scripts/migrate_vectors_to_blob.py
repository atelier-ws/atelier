#!/usr/bin/env python3
"""Convert legacy JSON-backed symbol_vectors stores to blob-only and reclaim disk.

Fresh indexes are already blob-only; this is for stores written before the
switch. For each DB it backfills the packed float32 ``vector_blob`` from the
stored JSON, drops the ``vector_json`` column, then VACUUMs to return the freed
pages to the OS (the one step the lazy in-engine migration skips, because VACUUM
needs up to one DB-size of temp space and a long exclusive lock).

Usage:
    uv run python scripts/migrate_vectors_to_blob.py DB [DB ...]
    uv run python scripts/migrate_vectors_to_blob.py --no-vacuum DB   # skip shrink

VACUUM needs free disk roughly equal to the DB size; skip it with --no-vacuum on
a tight disk and run it later when there is headroom.
"""

from __future__ import annotations

import json
import os
import sqlite3
import struct
import sys
import time


def _migrate(db_path: str, *, vacuum: bool) -> None:
    size0 = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA mmap_size = 2147483648")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(symbol_vectors)")}
    if "symbol_vectors" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        print(f"[skip] {db_path}: no symbol_vectors table")
        return
    if "vector_json" not in cols:
        print(f"[skip] {db_path}: already blob-only ({size0 / 1e6:.0f} MB)")
        return
    if "vector_blob" not in cols:
        conn.execute("ALTER TABLE symbol_vectors ADD COLUMN vector_blob BLOB")

    total = conn.execute("SELECT COUNT(*) FROM symbol_vectors WHERE vector_blob IS NULL").fetchone()[0]
    print(f"[migrate] {db_path}: {total} rows to pack ({size0 / 1e6:.0f} MB)", flush=True)
    t0 = time.perf_counter()
    done = 0
    batch = 20_000
    last_rowid = -1
    while True:
        rows = conn.execute(
            "SELECT rowid, vector_json FROM symbol_vectors "
            "WHERE vector_blob IS NULL AND rowid > ? ORDER BY rowid LIMIT ?",
            (last_rowid, batch),
        ).fetchall()
        if not rows:
            break
        last_rowid = int(rows[-1][0])
        updates: list[tuple[bytes, int]] = []
        for rowid, vjson in rows:
            try:
                payload = json.loads(str(vjson))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, list) or not payload:
                continue
            try:
                blob = struct.pack(f"{len(payload)}f", *(float(x) for x in payload))
            except (struct.error, TypeError, ValueError):
                continue
            updates.append((blob, int(rowid)))
        if updates:
            conn.executemany("UPDATE symbol_vectors SET vector_blob = ? WHERE rowid = ?", updates)
            conn.commit()
        done += len(rows)
        if done % 200_000 < batch:
            print(f"    {done}/{total} packed  {time.perf_counter() - t0:.0f}s", flush=True)

    conn.execute("DELETE FROM symbol_vectors WHERE vector_blob IS NULL")
    conn.execute("ALTER TABLE symbol_vectors DROP COLUMN vector_json")
    conn.commit()
    print(f"    dropped vector_json in {time.perf_counter() - t0:.0f}s", flush=True)

    if vacuum:
        print("    VACUUM (returning freed pages to OS)...", flush=True)
        tv = time.perf_counter()
        conn.isolation_level = None
        conn.execute("VACUUM")
        print(f"    VACUUM done in {time.perf_counter() - tv:.0f}s", flush=True)
    conn.close()
    size1 = os.path.getsize(db_path)
    print(f"[done] {db_path}: {size0 / 1e6:.0f} MB -> {size1 / 1e6:.0f} MB", flush=True)


def main(argv: list[str]) -> int:
    vacuum = True
    dbs = []
    for a in argv:
        if a == "--no-vacuum":
            vacuum = False
        else:
            dbs.append(a)
    if not dbs:
        print(__doc__)
        return 1
    for db in dbs:
        _migrate(db, vacuum=vacuum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
