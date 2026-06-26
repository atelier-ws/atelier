"""Clone, index, and mine query pairs for the 6 SWE-bench repos missing from
the original provision run (matplotlib, seaborn, flask, requests, pylint, sphinx).

Gold files are mined directly from mcp__atelier__edit calls in the dump files
(same approach as _mine_sessions.py) -- no swebench module required.
Clones HEAD since base_commits are unavailable without swebench.

Usage:
  uv run python scripts/_provision_missing_repos.py
"""

import json
import pathlib
import re
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine

try:
    from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor
except Exception:  # noqa: BLE001
    get_zoekt_supervisor = None

RUN = pathlib.Path("reports/benchmark/codebench/swe50_stress_run1")
OUT = pathlib.Path("benchmarks/codebench/data/bench_pairs_multi.json")
TID_RE = re.compile(r"^(.*?)_(?:atelier|baseline)_rep\d+\.flow_dump\.txt$")
GREP_RE = re.compile(r"mcp__plugin_atelier_atelier__grep\] (\{.*?\})", re.S)
TESTRE = re.compile(r"(^|/)(test_|tests?/|conftest)")

MISSING = {
    "matplotlib__matplotlib": "matplotlib/matplotlib",
    "mwaskom__seaborn": "mwaskom/seaborn",
    "pallets__flask": "pallets/flask",
    "psf__requests": "psf/requests",
    "pylint-dev__pylint": "pylint-dev/pylint",
    "sphinx-doc__sphinx": "sphinx-doc/sphinx",
}


def symbol_count(db: pathlib.Path) -> int:
    try:
        con = sqlite3.connect(str(db))
        n = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
        con.close()
        return int(n)
    except Exception:  # noqa: BLE001
        return -1


def mine_grep(dump: pathlib.Path) -> list[str]:
    out = []
    for blob in GREP_RE.findall(dump.read_text(errors="replace")):
        m = re.search(r'"regex":\s*"((?:[^"\\]|\\.)*)"', blob)
        if m:
            q = m.group(1).encode().decode("unicode_escape", "replace")
            if 3 <= len(q) <= 80:
                out.append(q)
    return out


def mine_edited_files(dump: pathlib.Path, ws: pathlib.Path) -> list[str]:
    """Extract files edited in the dump that exist in the workspace."""
    EDIT_RE = re.compile(r"mcp__plugin_atelier_atelier__edit\] (\{.*?\})", re.S)
    found: set[str] = set()
    for blob in EDIT_RE.findall(dump.read_text(errors="replace")):
        for path_match in re.finditer(r'"path":\s*"([^"]+)"', blob):
            p = path_match.group(1)
            if not p.endswith(".py"):
                continue
            if TESTRE.search(p):
                continue
            # make relative
            rel = p.lstrip("/")
            # strip leading workspace path component if present
            for part in ws.parts:
                prefix = part + "/"
                if rel.startswith(prefix):
                    rel = rel[len(prefix) :]
            if (ws / rel).exists():
                found.add(rel)
    return list(found)


def main() -> None:
    data = json.loads(OUT.read_text())
    existing_repos = data["repos"]
    existing_true = data["true_map"]
    existing_pairs = data["pairs"]

    new_pairs: list[list[str]] = []
    added_repos: dict[str, dict] = {}
    added_true: dict[str, list[str]] = {}

    for prefix, repo in MISSING.items():
        dumps = sorted(d for d in RUN.glob(f"{prefix}*_dump.txt") if TID_RE.match(d.name))
        if not dumps:
            print(f"[{prefix}] no dump files, skip", flush=True)
            continue

        ws = pathlib.Path(f"/tmp/idx_ws_{prefix}")
        db = pathlib.Path(f"/tmp/idx_{prefix}.db")

        if not ws.exists() or not any(ws.iterdir()):
            print(f"[{prefix}] cloning {repo} ...", flush=True)
            subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1", f"https://github.com/{repo}.git", str(ws)],
                check=True,
                timeout=1200,
            )
        else:
            print(f"[{prefix}] workspace exists", flush=True)

        if not db.exists():
            print(f"[{prefix}] indexing -> {db} ...", flush=True)
            t0 = time.time()
            try:
                CodeContextEngine(ws, db_path=db, autosync_enabled=False).index_repo()
            except Exception as e:  # noqa: BLE001
                print(f"[{prefix}] INDEX FAILED: {e}", flush=True)
                continue
            print(f"[{prefix}] done {time.time() - t0:.0f}s symbols={symbol_count(db)}", flush=True)
        else:
            print(f"[{prefix}] index exists symbols={symbol_count(db)}", flush=True)

        if get_zoekt_supervisor is not None:
            try:
                get_zoekt_supervisor(ws)
            except Exception:  # noqa: BLE001
                pass

        # Mine queries + gold files from dumps
        by_task: dict[str, dict] = {}
        for d in dumps:
            tid = TID_RE.match(d.name).group(1)  # type: ignore[union-attr]
            queries = mine_grep(d)
            gold = mine_edited_files(d, ws)
            if queries and gold:
                by_task.setdefault(tid, {"queries": [], "gold": set()})
                by_task[tid]["queries"].extend(queries)
                by_task[tid]["gold"].update(gold)

        kept = 0
        for tid, d in by_task.items():
            gold = list(d["gold"])
            if not gold:
                continue
            added_true[tid] = gold
            for q in d["queries"]:
                new_pairs.append([q, tid, prefix])
                kept += 1

        added_repos[prefix] = {"ws": str(ws), "db": str(db), "anchor": "HEAD", "base_commit": ""}
        print(f"[{prefix}] {kept} pairs from {len(by_task)} tasks", flush=True)

    if not new_pairs:
        print("[provision] nothing to add", flush=True)
        return

    existing_repos.update(added_repos)
    existing_true.update(added_true)
    merged = existing_pairs + new_pairs
    uniq = len({(q, p) for q, _, p in merged})
    print(f"[provision] +{len(new_pairs)} pairs across {len(added_repos)} new repos", flush=True)
    print(f"[provision] total: {len(merged)} pairs | {uniq} unique (query,repo)", flush=True)
    data["pairs"] = merged
    data["true_map"] = existing_true
    data["repos"] = existing_repos
    OUT.write_text(json.dumps(data))
    print(f"[provision] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
