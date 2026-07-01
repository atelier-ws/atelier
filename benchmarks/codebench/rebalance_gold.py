"""Rebalance gold pair files so every repo has exactly TARGET pairs.

- Over-target repos: random-sample down.
- Under-target repos: mine more pairs from their index DBs.
  * def/content gold: symbol-name queries
  * semantic gold: docstring first-sentence queries

Usage:
    python3.14 benchmarks/codebench/rebalance_gold.py [--target 100] [--sem-target 40] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--target", type=int, default=100, help="Target per repo for def/content gold")
ap.add_argument("--sem-target", type=int, default=40, help="Target per repo for semantic gold")
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--dry-run", action="store_true")
args = ap.parse_args()

DATA = Path("benchmarks/codebench/data")
rng = random.Random(args.seed)

# ---------------------------------------------------------------------------
# DB paths: canonical DB per repo slug
# ---------------------------------------------------------------------------
_DB_ROOTS = ["/tmp"]


def _find_db(repo_prefix: str, meta: dict) -> Path | None:
    # 1. explicit db in meta
    if meta.get("db"):
        p = Path(meta["db"])
        if p.exists() and p.stat().st_size > 0:
            return p
    # 2. idx_* style
    slug = repo_prefix.replace("__", "__")
    for root in _DB_ROOTS:
        p = Path(root) / f"idx_{slug}.db"
        if p.exists() and p.stat().st_size > 0:
            return p
    # 3. eval_* style (pick largest)
    owner, repo = (repo_prefix.split("__") + [""])[:2]
    candidates = sorted(Path("/tmp").glob(f"eval_{owner}_{repo}_*.db"), key=lambda x: x.stat().st_size, reverse=True)
    for c in candidates:
        if c.stat().st_size > 0:
            return c
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tid(kind: str, file_path: str, symbol_name: str) -> str:
    h = hashlib.sha256(f"{kind}:{file_path}:{symbol_name}".encode()).hexdigest()[:16]
    return f"{kind}-{h}"


_CODE_RE = re.compile(r"[{}<>()\[\]|=]|\b(?:def|class|import|return|self)\b")
_SHORT = 25


def _clean_doc_sentence(doc: str) -> str | None:
    """Extract the first meaningful sentence from a docstring."""
    if not doc:
        return None
    # strip leading whitespace / param markers
    text = doc.strip().lstrip(":")
    # first sentence
    first = re.split(r"(?<=[.!?])\s", text)[0].strip()
    # reject if too short, looks like code, or is just the symbol name
    if len(first) < _SHORT:
        return None
    if _CODE_RE.search(first):
        return None
    if first.startswith(("Args:", "Parameters", "Returns:", "Note:", "Example")):
        return None
    return first[:120]


def _name_queries(sym_name: str, kind: str) -> list[str]:
    """Symbol-name based queries for def/content gold."""
    name = sym_name.strip()
    if not name or len(name) < 3:
        return []
    qs = [name]
    if kind in ("function", "method"):
        qs.append(f"def {name}")
    elif kind == "class":
        qs.append(f"class {name}")
    # strip common prefix
    for pfx in (
        "get_",
        "set_",
        "is_",
        "has_",
        "to_",
        "from_",
        "_get_",
        "build_",
        "check_",
        "make_",
        "create_",
        "handle_",
        "parse_",
    ):
        if name.lower().startswith(pfx) and len(name) > len(pfx) + 2:
            qs.append(name[len(pfx) :])
            break
    return qs


def mine_pairs(
    db_path: Path, repo_prefix: str, gold_kind: str, existing_tids: set[str], target: int
) -> tuple[list, dict]:
    """Mine `target` new pairs from the repo's index DB."""
    con = sqlite3.connect(str(db_path))
    rows = con.execute(
        "SELECT file_path, symbol_name, kind, doc_summary "
        "FROM symbols WHERE file_path IS NOT NULL AND symbol_name IS NOT NULL"
    ).fetchall()
    con.close()

    # shuffle for diversity
    rows_list = list(rows)
    rng.shuffle(rows_list)

    new_pairs: list = []
    new_true_map: dict = {}

    for fp, sname, kind, doc in rows_list:
        if len(new_pairs) >= target:
            break
        kind = kind or "function"

        if gold_kind == "semantic":
            query = _clean_doc_sentence(doc or "")
            if not query:
                continue
            # skip if query is suspiciously close to the symbol name
            if sname and sname.lower() in query.lower():
                continue
        else:
            variants = _name_queries(sname, kind)
            if not variants:
                continue
            query = variants[len(new_pairs) % len(variants)]

        tid = _tid(gold_kind, fp, sname)
        if tid in existing_tids:
            continue

        new_pairs.append([query, tid, repo_prefix])
        new_true_map[tid] = [fp]
        existing_tids.add(tid)

    return new_pairs, new_true_map


# ---------------------------------------------------------------------------
# Process each gold file
# ---------------------------------------------------------------------------

GOLD_FILES = [
    ("def", args.target, DATA / "bench_pairs_def_gold.json"),
    ("content", args.target, DATA / "bench_pairs_content_gold.json"),
]

for gold_kind, target, gold_path in GOLD_FILES:
    if not gold_path.exists():
        print(f"SKIP {gold_path.name} (not found)")
        continue

    d = json.loads(gold_path.read_text())
    pairs: list = d["pairs"]
    true_map: dict = d["true_map"]
    repos: dict = d["repos"]

    by_repo: dict[str, list] = defaultdict(list)
    for pair in pairs:
        by_repo[pair[2]].append(pair)

    existing_tids: set[str] = set(true_map.keys())
    new_pairs: list = []
    new_true_map: dict = {}

    print(f"\n{'=' * 65}")
    print(f"  {gold_path.name}  target={target}/repo  kind={gold_kind}")

    for repo_prefix in sorted(repos.keys()):
        repo_pairs = by_repo.get(repo_prefix, [])
        current = len(repo_pairs)
        meta = repos[repo_prefix]

        if current >= target:
            sampled = rng.sample(repo_pairs, target)
        else:
            sampled = list(repo_pairs)  # keep all
            need = target - current
            db = _find_db(repo_prefix, meta)
            if db:
                mined, mined_tm = mine_pairs(db, repo_prefix, gold_kind, existing_tids, need)
                sampled.extend(mined)
                new_true_map.update(mined_tm)
                added = len(mined)
            else:
                added = 0
                print(f"  WARN no DB found for {repo_prefix}")

        new_pairs.extend(sampled)
        for _, tid, _ in sampled:
            if tid in true_map:
                new_true_map[tid] = true_map[tid]

        action = (
            f"+{len(sampled) - current} mined"
            if len(sampled) > current
            else ("downsampled" if current > target else "ok")
        )
        print(f"  {current:>4} -> {len(sampled):>3}  ({action:<18})  {repo_prefix.split('__')[-1]}")

    # verify
    final: dict[str, int] = defaultdict(int)
    for _, _, rp in new_pairs:
        final[rp] += 1
    counts = list(final.values())
    print(f"  Total: {len(pairs)} -> {len(new_pairs)}  min={min(counts)}  max={max(counts)}  repos={len(final)}")

    if not args.dry_run:
        gold_path.write_text(json.dumps({**d, "pairs": new_pairs, "true_map": new_true_map}, indent=2))
        print(f"  Saved -> {gold_path}")
    else:
        print("  [dry-run]")

print("\nDone.")
