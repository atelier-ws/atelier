"""Curate an 'expensive' SWE-bench Verified slice from the Opus-4.5-solvable pool.

Ranks the 396 solvable tasks by an agent-cost proxy (validated rho=+0.67 vs our
real observed median cost) and writes a repo-diversified expensive set.
"""

from __future__ import annotations

import collections
import logging
import pathlib

logging.disable(logging.INFO)
from benchmarks.codebench.multiswe import changed_file_count  # noqa: E402
from swebench.harness.utils import load_swebench_dataset  # noqa: E402

HERE = pathlib.Path(__file__).parent
DIFF = {"<15 min fix": 0.0, "15 min - 1 hour": 0.34, "1-4 hours": 0.67, ">4 hours": 1.0}


def patch_lines(p: str) -> int:
    return sum(
        1
        for line in p.splitlines()
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
    )


def main() -> None:
    resolved = [ln.strip() for ln in (HERE / "opus45_verified_resolved.txt").read_text().splitlines() if ln.strip()]
    suite = {ln.strip() for ln in (HERE / "verified.txt").read_text().splitlines() if ln.strip()}
    rows = load_swebench_dataset("SWE-bench/SWE-bench_Verified", "test", resolved)

    recs = []
    for r in rows:
        iid = str(r["instance_id"])
        g = str(r.get("patch") or "")
        recs.append(
            {
                "iid": iid,
                "repo": iid.split("__", 1)[0],
                "diff": r.get("difficulty") or "?",
                "dscore": DIFF.get(r.get("difficulty"), 0.3),
                "files": changed_file_count(g),
                "plines": patch_lines(g),
                "tplines": patch_lines(str(r.get("test_patch") or "")),
                "pchars": len(str(r.get("problem_statement") or "")),
            }
        )

    def norm(k: str) -> None:
        v = [x[k] for x in recs]
        lo, hi = min(v), max(v)
        rng = (hi - lo) or 1
        for x in recs:
            x[k + "_n"] = (x[k] - lo) / rng

    for k in ("plines", "files", "pchars", "tplines"):
        norm(k)
    for x in recs:
        x["score"] = (
            0.34 * x["dscore"]
            + 0.26 * x["plines_n"]
            + 0.18 * x["pchars_n"]
            + 0.12 * x["files_n"]
            + 0.10 * x["tplines_n"]
        )
    recs.sort(key=lambda x: -x["score"])

    cap: collections.Counter = collections.Counter()
    pick = []
    for x in recs:
        if x["iid"] in suite:
            continue
        if x["dscore"] < 0.34:  # drop trivial (<15 min) tasks
            continue
        if cap[x["repo"]] >= 3:  # repo diversity cap
            continue
        cap[x["repo"]] += 1
        pick.append(x)
        if len(pick) >= 12:
            break

    out = HERE / "verified_expensive.txt"
    out.write_text("\n".join(x["iid"] for x in pick) + "\n")
    print(f"WROTE {out}  ({len(pick)} tasks)  repo mix: {dict(cap)}")
    print(f"\n{'instance':32s} {'score':>5s} {'difficulty':12s} {'files':>5s} {'patchL':>6s} {'probKB':>6s}")
    for x in pick:
        print(
            f"{x['iid']:32s} {x['score']:.3f} {x['diff']:12s} {x['files']:5d} {x['plines']:6d} {x['pchars'] / 1000:6.1f}"
        )


if __name__ == "__main__":
    main()
