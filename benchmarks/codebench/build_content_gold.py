"""Build a CONTENT/usage gold: gold = files whose CONTENT matches the query.

Complements bench_pairs_def_gold.json (definition gold). The bench queries are
agent greps, so the content gold = the files ``rg <query>`` returns -- the
usage/content-recall target where trigram search (Zoekt) earns its keep, vs the
definition target where FTS-symbol search wins.

gold = files matching the query as a regex (falls back to fixed-string on a bad
pattern), kept only when the match set is specific (1..--max-files files). Broad
(too many matches) or no-match queries are dropped. Output is tid-keyed, so the
existing harnesses work via ``--pairs`` / ``FITNESS_PAIRS`` / ``EVAL_PAIRS``.

Usage::

    uv run python benchmarks/codebench/build_content_gold.py \\
        --in benchmarks/codebench/data/bench_pairs_swebench_gold.json \\
        --out benchmarks/codebench/data/bench_pairs_content_gold.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _norm(p: str) -> str:
    return p.replace("\\", "/")


# Paths to exclude from content gold (benchmark data, not source code).
_EXCLUDE_PREFIXES = ("benchmarks/codebench/data/",)


def _is_excluded(path: str) -> bool:
    return any(path.startswith(pfx) for pfx in _EXCLUDE_PREFIXES)


def _tid(prefix: str, query: str) -> str:
    return "content-" + hashlib.blake2s(f"{prefix}\x00{query}".encode()).hexdigest()[:16]


def _rg_files(pattern: str, ws: Path) -> list[str]:
    """Files under *ws* matching *pattern* (regex; fixed-string fallback)."""

    def run(extra: list[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                ["rg", "-l", "--no-messages", "--max-filesize", "2M", *extra, "--", pattern, str(ws)],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return None

    proc = run([])
    if proc is not None and proc.returncode == 2:  # bad regex -> literal
        proc = run(["-F"])
    if proc is None or proc.returncode not in (0, 1):
        return []
    ws_abs = ws.resolve()
    out: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rel = _norm(str(Path(line).resolve().relative_to(ws_abs)))
        except ValueError:
            rel = _norm(line)
        if _is_excluded(rel):
            continue
        out.append(rel)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="benchmarks/codebench/data/bench_pairs_swebench_gold.json")
    ap.add_argument("--out", default="benchmarks/codebench/data/bench_pairs_content_gold.json")
    ap.add_argument("--max-files", type=int, default=10, help="drop queries matching more than this many files")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    with open(args.src) as fh:
        data = json.load(fh)
    repos = data["repos"]
    by_repo: dict[str, list[str]] = {}
    for q, _old_tid, prefix in data["pairs"]:
        by_repo.setdefault(prefix, [])
        if q not in by_repo[prefix]:
            by_repo[prefix].append(q)

    out_pairs: list[list[str]] = []
    true_map: dict[str, list[str]] = {}
    print(f"{'repo':28s} {'queries':>8} {'scorable':>9} {'dropped':>8} {'avg_gold':>9}", file=sys.stderr)
    tot_q = tot_s = 0
    for prefix, queries in sorted(by_repo.items()):
        ws = repos.get(prefix, {}).get("ws")
        if not ws or not Path(ws).is_dir():
            print(f"{prefix:28s}  (no workspace -> skip {len(queries)} queries)", file=sys.stderr)
            continue
        ws_path = Path(ws)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(lambda q, _ws=ws_path: _rg_files(q, _ws), queries))
        scorable = 0
        gsizes: list[int] = []
        for q, files in zip(queries, results, strict=True):
            if not files or len(files) > args.max_files:
                continue
            tid = _tid(prefix, q)
            out_pairs.append([q, tid, prefix])
            true_map[tid] = sorted(files)
            scorable += 1
            gsizes.append(len(files))
        tot_q += len(queries)
        tot_s += scorable
        avg = sum(gsizes) / len(gsizes) if gsizes else 0.0
        print(f"{prefix:28s} {len(queries):8d} {scorable:9d} {len(queries) - scorable:8d} {avg:9.1f}", file=sys.stderr)

    out = {
        "pairs": out_pairs,
        "true_map": true_map,
        "repos": repos,
        "gold_kind": "content",
        "params": {"max_files": args.max_files},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh)
    print(
        f"\nwrote {args.out}: {tot_s}/{tot_q} queries scorable ({100 * tot_s / max(tot_q, 1):.0f}%), {len(true_map)} golds",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
