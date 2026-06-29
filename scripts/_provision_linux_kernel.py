"""Provision the Linux kernel as a retrieval-bench repo + mine its definition gold.

The kernel is far too large to provision whole (full tree = ~64k C files, ~30M LOC
across drivers/ + arch/ that are hardware-specific and repetitive). We scope to the
**core subsystems** -- the stable, symbol-rich OS core that is representative without
the long driver/arch tail:

    kernel/ mm/ fs/ block/ ipc/ lib/ security/ crypto/ init/ virt/ include/

That is ~11k C files / ~4.5M LOC -- bigger than any diverse-5 repo (a real scale
stress test) yet tractable: Atelier indexes it in ~4 min (~1.24M symbols) and
codebase-memory-mcp in seconds.

The diverse-5 gold is mined from SWE-bench grep dumps; the kernel has none. But the
gold only needs (a) an Atelier symbol index and (b) a `bench_pairs_multi.json`-shaped
query universe. We mine that universe **from the symbol index itself** -- exactly the
shape `build_definition_gold.py` scores: bare function/struct names and clean
alternations of them. Each mined query is a real, specific kernel symbol whose
definition file is unambiguous, so the SAME purity / scatter / max_def gates in
`build_definition_gold.py` apply and the gold is built identically to the diverse-5.

Deterministic (seeded) so the gold is reproducible.

Usage::

    # 1) clone + scope + index (idempotent; skips work that already exists)
    uv run --no-sync python scripts/_provision_linux_kernel.py --prepare
    # 2) mine queries -> multi.json, then derive the definition gold
    uv run --no-sync python scripts/_provision_linux_kernel.py --mine

Outputs (merged INTO the existing bench files so every arm sees the kernel):
    benchmarks/codebench/data/bench_pairs_linux.json       (kernel-only multi)
    benchmarks/codebench/data/bench_pairs_linux_def_gold.json (kernel-only def gold)
and, with --merge, appends the kernel repo+pairs into the shared
    benchmarks/codebench/data/bench_pairs_def_gold.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "src")

PREFIX = "torvalds__linux"
FULL_CLONE = Path("/tmp/idx_ws_linux")
WS = Path("/tmp/idx_ws_linux_core")
DB = Path("/tmp/idx_linux_core.db")
CORE_SUBTREES = ["kernel", "mm", "fs", "block", "ipc", "lib", "security", "crypto", "init", "virt", "include"]
KERNEL_URL = "https://github.com/torvalds/linux.git"

DATA = Path("benchmarks/codebench/data")
MULTI = DATA / "bench_pairs_linux.json"
GOLD = DATA / "bench_pairs_linux_def_gold.json"
SHARED_GOLD = DATA / "bench_pairs_def_gold.json"

# Symbol kinds that name a real definition (skip noise like variables/params/fields).
_DEF_KINDS = {"function", "struct", "class", "enum", "union", "typedef", "macro", "method"}
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{3,}$")
# Identifiers too generic to make a discriminating query (kernel is full of these).
_GENERIC = {
    "init",
    "exit",
    "open",
    "close",
    "read",
    "write",
    "start",
    "stop",
    "show",
    "store",
    "probe",
    "remove",
    "alloc",
    "free",
    "lock",
    "unlock",
    "get",
    "put",
    "set",
    "reset",
    "enable",
    "disable",
    "suspend",
    "resume",
    "register",
    "unregister",
    "handler",
    "create",
    "destroy",
    "update",
    "flush",
    "sync",
    "name",
    "size",
    "data",
    "info",
    "type",
    "node",
}


def _run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)  # type: ignore[arg-type]


def prepare() -> None:
    """Clone (shallow), scope to the core subtrees, and Atelier-index the workspace."""
    if not WS.exists() or not any(WS.iterdir()):
        if not FULL_CLONE.exists():
            print(f"[linux] shallow clone {KERNEL_URL} -> {FULL_CLONE}", flush=True)
            r = _run(["git", "clone", "--quiet", "--depth", "1", KERNEL_URL, str(FULL_CLONE)], timeout=3600)
            if r.returncode != 0:
                raise RuntimeError(r.stderr[:800])
        WS.mkdir(parents=True, exist_ok=True)
        print(f"[linux] scoping core subtrees -> {WS}", flush=True)
        for d in CORE_SUBTREES:
            src, dst = FULL_CLONE / d, WS / d
            if src.is_dir() and not dst.exists():
                src.rename(dst)
        mk = FULL_CLONE / "Makefile"
        if mk.exists() and not (WS / "Makefile").exists():
            (WS / "Makefile").write_bytes(mk.read_bytes())
    n_c = sum(1 for _ in WS.rglob("*.c"))
    n_h = sum(1 for _ in WS.rglob("*.h"))
    print(f"[linux] scoped ws: {n_c} .c + {n_h} .h files", flush=True)
    if not DB.exists() or DB.stat().st_size < 1_000_000:
        from atelier.core.capabilities.code_context.engine import CodeContextEngine

        print(f"[linux] indexing -> {DB} (this takes a few minutes) ...", flush=True)
        t0 = time.time()
        CodeContextEngine(WS, db_path=DB, autosync_enabled=False).index_repo()
        print(f"[linux] index done {time.time() - t0:.0f}s symbols={_symbol_count(DB)}", flush=True)
    else:
        print(f"[linux] index exists, symbols={_symbol_count(DB)}", flush=True)


def _symbol_count(db: Path) -> int:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    n = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
    con.close()
    return int(n)


def mine(
    *,
    n_single: int,
    n_alt: int,
    alt_size: int,
    max_def: int,
    seed: int,
) -> None:
    """Mine a (query, gold-file) universe from the symbol index, then derive the def gold.

    Two query shapes -- the same two the diverse-5 gold is dominated by:
      * single-token: a bare specific symbol name (defined in <= max_def files).
      * alternation : ``a|b|c`` of specific symbols that share a definition file
        (so the alternation has an unambiguous gold), mirroring the SWE grep style.
    """
    rng = random.Random(seed)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute("SELECT symbol_name, file_path, kind FROM symbols").fetchall()
    con.close()

    # name -> set(files), restricted to real definition kinds + specific identifiers.
    name_files: dict[str, set[str]] = defaultdict(set)
    file_names: dict[str, set[str]] = defaultdict(set)
    for name, fp, kind in rows:
        if not name or not fp or (kind or "").lower() not in _DEF_KINDS:
            continue
        if not _IDENT_RE.match(name) or name.lower() in _GENERIC:
            continue
        name_files[name].add(fp.replace("\\", "/"))
        file_names[fp.replace("\\", "/")].add(name)

    # Specific symbols: defined in a small number of files (discriminating).
    specific = [n for n, fs in name_files.items() if 1 <= len(fs) <= max_def]
    rng.shuffle(specific)
    print(f"[linux] {len(name_files)} def-symbols, {len(specific)} specific (<= {max_def} files)", flush=True)

    queries: list[str] = []
    seen: set[str] = set()
    # 1) single-token queries
    for name in specific:
        if len(queries) >= n_single:
            break
        if name not in seen:
            seen.add(name)
            queries.append(name)

    # 2) alternation queries: pick a file with >= alt_size specific symbols, OR them.
    files_with_specifics = [
        (f, sorted(ns & set(specific))) for f, ns in file_names.items() if len(ns & set(specific)) >= alt_size
    ]
    rng.shuffle(files_with_specifics)
    n_made = 0
    for _f, names in files_with_specifics:
        if n_made >= n_alt:
            break
        picks = rng.sample(names, alt_size)
        q = "|".join(picks)
        if q not in seen:
            seen.add(q)
            queries.append(q)
            n_made += 1

    print(f"[linux] mined {len(queries)} queries ({n_single} single + {n_made} alternation)", flush=True)

    # Emit the bench_pairs_multi shape. true_map is a placeholder (the SWE-edit gold
    # we don't have); build_definition_gold.py derives the real gold from the index.
    pairs = [[q, f"lk-{i}", PREFIX] for i, q in enumerate(queries)]
    repos_meta = {PREFIX: {"ws": str(WS), "db": str(DB), "anchor": "HEAD", "base_commit": "HEAD"}}
    MULTI.parent.mkdir(parents=True, exist_ok=True)
    with open(MULTI, "w") as fh:
        json.dump({"pairs": pairs, "true_map": {p[1]: [] for p in pairs}, "repos": repos_meta}, fh)
    print(f"[linux] wrote {MULTI}", flush=True)

    # Derive the definition gold with the SAME builder/gates as the diverse-5.
    print("[linux] deriving definition gold via build_definition_gold.py ...", flush=True)
    r = _run(
        [
            sys.executable,
            "benchmarks/codebench/build_definition_gold.py",
            "--in",
            str(MULTI),
            "--out",
            str(GOLD),
        ],
        timeout=600,
    )
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        raise RuntimeError("build_definition_gold failed")
    with open(GOLD) as fh:
        g = json.load(fh)
    print(f"[linux] gold: {len(g['pairs'])} scorable pairs, {len(g['true_map'])} golds", flush=True)


def merge_into_shared() -> None:
    """Append the kernel repo + pairs + golds into the shared diverse gold file."""
    with open(GOLD) as fh:
        lk = json.load(fh)
    with open(SHARED_GOLD) as fh:
        shared = json.load(fh)
    shared["repos"].update(lk["repos"])
    existing = {(q, p) for q, _t, p in shared["pairs"]}
    added = 0
    for q, tid, p in lk["pairs"]:
        if (q, p) not in existing:
            shared["pairs"].append([q, tid, p])
            shared["true_map"][tid] = lk["true_map"][tid]
            added += 1
    with open(SHARED_GOLD, "w") as fh:
        json.dump(shared, fh)
    print(f"[linux] merged {added} kernel pairs into {SHARED_GOLD}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true", help="clone + scope + index the kernel core")
    ap.add_argument("--mine", action="store_true", help="mine queries and derive the def gold")
    ap.add_argument("--merge", action="store_true", help="append kernel into the shared def gold")
    ap.add_argument("--n-single", type=int, default=400)
    ap.add_argument("--n-alt", type=int, default=200)
    ap.add_argument("--alt-size", type=int, default=3)
    ap.add_argument("--max-def", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20260629)
    args = ap.parse_args()
    if not (args.prepare or args.mine or args.merge):
        ap.error("pass at least one of --prepare / --mine / --merge")
    if args.prepare:
        prepare()
    if args.mine:
        mine(
            n_single=args.n_single,
            n_alt=args.n_alt,
            alt_size=args.alt_size,
            max_def=args.max_def,
            seed=args.seed,
        )
    if args.merge:
        merge_into_shared()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
