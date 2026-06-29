"""Re-derive coherent retrieval gold for the benchmark / training pairs.

Problem: the original gold = SWE-bench patch-changed files, but the queries are
agent greps for symbols that are frequently DEFINED IN OTHER FILES. So the gold
files do not contain the queried term at all and no retriever can surface them
(verified: query 'typecast_timestamp' -> gold operations.py, but the symbol
lives in utils.py). That makes recall/MRR measure a query<->gold mismatch, not
retrieval quality.

Fix: gold = the indexed file(s) that DEFINE the queried symbol(s). Queries whose
identifiers do not resolve to a specific symbol (too generic, e.g. ``def
__init__``, or not indexed) are dropped. Output is a coherent retrieval set:
``query -> file(s) actually containing it``.

Works for both the JSON bench format (pairs/true_map/repos) and the JSONL
training corpus (one record per line with query/gold_files/repo_prefix).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "src")

from atelier.core.capabilities.code_context import CodeContextEngine

_KEYWORDS = {
    "def",
    "class",
    "async",
    "await",
    "return",
    "self",
    "cls",
    "import",
    "from",
    "for",
    "while",
    "if",
    "elif",
    "else",
    "try",
    "except",
    "finally",
    "with",
    "as",
    "in",
    "is",
    "and",
    "or",
    "not",
    "none",
    "true",
    "false",
    "lambda",
    "yield",
    "raise",
    "assert",
    "pass",
    "break",
    "continue",
    "global",
    "nonlocal",
    "del",
    "test",
    "tests",
    "the",
    "def_",
}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_MAX_FILES_PER_IDENT = 12  # an identifier in more files than this is too ambiguous
_MAX_GOLD = 10


def extract_identifiers(query: str) -> list[str]:
    out: list[str] = []
    for token in _IDENT.findall(query):
        if token.lower() in _KEYWORDS:
            continue
        if token not in out:
            out.append(token)
    return out


def resolve_gold(con: sqlite3.Connection, repo_id: str, idents: list[str]) -> list[str]:
    """Files defining any queried symbol; specificity-weighted, ambiguous dropped."""
    score: dict[str, int] = {}
    for ident in idents:
        rows = con.execute(
            "SELECT DISTINCT file_path FROM symbols WHERE repo_id = ? AND symbol_name = ?",
            (repo_id, ident),
        ).fetchall()
        if rows and len(rows) <= _MAX_FILES_PER_IDENT:
            for (file_path,) in rows:
                score[file_path] = score.get(file_path, 0) + 1
    return [f for f, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))][:_MAX_GOLD]


def _engine_repo_id(meta: dict) -> tuple[str, str]:
    db = str(meta["db"])
    engine = CodeContextEngine(Path(meta["ws"]), db_path=Path(db), autosync_enabled=False)
    return str(engine.repo_id), db


def fix_json(inp: Path, out: Path) -> None:
    data = json.loads(inp.read_text(encoding="utf-8"))
    repos = data["repos"]
    by_repo: dict[str, list[str]] = {}
    for query, _tid, prefix in data["pairs"]:
        bucket = by_repo.setdefault(prefix, [])
        if query not in bucket:
            bucket.append(query)

    new_pairs: list[list[str]] = []
    new_true: dict[str, list[str]] = {}
    stats: dict[str, dict[str, float]] = {}
    for prefix in sorted(by_repo):
        meta = repos.get(prefix)
        if not isinstance(meta, dict) or not meta.get("db"):
            continue
        repo_id, db = _engine_repo_id(meta)
        con = sqlite3.connect(db)
        kept = dropped = 0
        gold_sizes: list[int] = []
        for index, query in enumerate(sorted(by_repo[prefix])):
            gold = resolve_gold(con, repo_id, extract_identifiers(query))
            if not gold:
                dropped += 1
                continue
            tid = f"q_{prefix}_{index}"
            new_true[tid] = gold
            new_pairs.append([query, tid, prefix])
            gold_sizes.append(len(gold))
            kept += 1
        con.close()
        stats[prefix] = {
            "kept": kept,
            "dropped": dropped,
            "avg_gold": round(sum(gold_sizes) / max(len(gold_sizes), 1), 2),
        }
        print(f"  {prefix:<28} kept={kept:<4} dropped={dropped:<4} avg_gold={stats[prefix]['avg_gold']}", flush=True)

    out.write_text(json.dumps({"pairs": new_pairs, "true_map": new_true, "repos": repos}), encoding="utf-8")
    total_kept = sum(int(s["kept"]) for s in stats.values())
    total_drop = sum(int(s["dropped"]) for s in stats.values())
    print(
        f"[fix] wrote {out} | kept={total_kept} dropped={total_drop} ({total_kept / max(total_kept + total_drop, 1):.0%} kept)"
    )


def fix_jsonl(inp: Path, out: Path, repo_metadata: Path) -> None:
    meta_all = json.loads(repo_metadata.read_text(encoding="utf-8")).get("repos", {})
    records = [json.loads(line) for line in inp.read_text(encoding="utf-8").splitlines() if line.strip()]
    # one connection per repo
    repo_ctx: dict[str, tuple[sqlite3.Connection, str]] = {}
    kept = dropped = 0
    with out.open("w", encoding="utf-8") as handle:
        for record in records:
            prefix = str(record.get("repo_prefix") or "")
            meta = meta_all.get(prefix)
            if not isinstance(meta, dict) or not meta.get("db"):
                dropped += 1
                continue
            if prefix not in repo_ctx:
                repo_id, db = _engine_repo_id(meta)
                repo_ctx[prefix] = (sqlite3.connect(db), repo_id)
            con, repo_id = repo_ctx[prefix]
            gold = resolve_gold(con, repo_id, extract_identifiers(str(record.get("query") or "")))
            if not gold:
                dropped += 1
                continue
            record["gold_files"] = gold
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            kept += 1
    for con, _ in repo_ctx.values():
        con.close()
    print(f"[fix] wrote {out} | kept={kept} dropped={dropped} ({kept / max(kept + dropped, 1):.0%} kept)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="inp", default="benchmarks/codebench/data/bench_pairs_multi.json")
    parser.add_argument("--out", default="benchmarks/codebench/data/bench_pairs_multi_fixed.json")
    parser.add_argument("--jsonl", action="store_true", help="Input is the JSONL training corpus.")
    parser.add_argument(
        "--repo-metadata",
        default="experiments/retrieval_symbol_vote/repo_metadata.json",
        help="For JSONL repo db lookup.",
    )
    args = parser.parse_args()
    if args.jsonl:
        fix_jsonl(Path(args.inp), Path(args.out), Path(args.repo_metadata))
    else:
        fix_json(Path(args.inp), Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
