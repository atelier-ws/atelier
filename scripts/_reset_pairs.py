"""Reset /tmp/bench_pairs_multi.json to clean SWE-bench baseline.

Re-mines grep queries from the flow dump files without needing swebench.
Preserves true_map and repos metadata from the existing file.

Usage:
  uv run python scripts/_reset_pairs.py
"""

import json
import pathlib
import re
import sys

RUN = pathlib.Path("reports/benchmark/codebench/swe50_stress_run1")
TID_RE = re.compile(r"^(.*?)_(?:atelier|baseline)_rep\d+\.flow_dump\.txt$")
GREP_RE = re.compile(r"mcp__plugin_atelier_atelier__grep\] (\{.*?\})", re.S)
OUT = pathlib.Path("/tmp/bench_pairs_multi.json")

PREFIX2REPO = [
    "django__django",
    "pytest-dev__pytest",
    "astropy__astropy",
    "sympy__sympy",
    "scikit-learn__scikit-learn",
    "pydata__xarray",
]


def mine_grep_queries(dump: pathlib.Path) -> list[str]:
    out = []
    for blob in GREP_RE.findall(dump.read_text(errors="replace")):
        m = re.search(r'"regex":\s*"((?:[^"\\]|\\.)*)"', blob)
        if m:
            q = m.group(1).encode().decode("unicode_escape", "replace")
            if 3 <= len(q) <= 80:
                out.append(q)
    return out


def main() -> None:
    existing = json.loads(OUT.read_text())
    true_map = existing["true_map"]
    repos = existing["repos"]
    # Drop atelier repo from repos meta for clean baseline
    swe_repos = {k: v for k, v in repos.items() if k != "atelier__atelier"}

    pairs: list[list[str]] = []
    for prefix in PREFIX2REPO:
        dumps = sorted(d for d in RUN.glob(f"{prefix}*_dump.txt") if TID_RE.match(d.name))
        by_task: dict[str, list[str]] = {}
        for d in dumps:
            tid = TID_RE.match(d.name).group(1)  # type: ignore[union-attr]
            for q in mine_grep_queries(d):
                by_task.setdefault(tid, []).append(q)
        kept = 0
        for tid, qs in by_task.items():
            if tid in true_map:
                for q in qs:
                    pairs.append([q, tid, prefix])
                    kept += 1
        print(f"  {prefix}: {kept} pairs", flush=True)

    print(f"total: {len(pairs)} pairs across {len(true_map)} tasks", flush=True)
    OUT.write_text(json.dumps({"pairs": pairs, "true_map": true_map, "repos": swe_repos}))
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    sys.path.insert(0, "src")
    main()
