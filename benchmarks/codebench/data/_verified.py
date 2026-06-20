"""One-off: pull Opus-4.5 Verified resolved IDs, persist, and print distribution."""

from __future__ import annotations

import collections
import json
import pathlib
import urllib.request

URL = (
    "https://raw.githubusercontent.com/SWE-bench/experiments/main/"
    "evaluation/verified/20251215_livesweagent_claude-opus-4-5/results/results.json"
)


def repo_of(iid: str) -> str:
    return iid.split("__", 1)[0]


def main() -> None:
    data = json.loads(urllib.request.urlopen(URL, timeout=60).read())
    resolved = sorted(data.get("resolved", []))
    out = pathlib.Path(__file__).parent / "opus45_verified_resolved.txt"
    out.write_text("\n".join(resolved) + "\n", encoding="utf-8")
    print(f"resolved: {len(resolved)}  ->  {out}")

    by_repo = collections.Counter(repo_of(i) for i in resolved)
    print("by repo:", dict(by_repo.most_common()))

    # changed-file counts from the real Verified gold patches
    from benchmarks.codebench.multiswe import changed_file_count
    from swebench.harness.utils import load_swebench_dataset

    rows = load_swebench_dataset("SWE-bench/SWE-bench_Verified", "test", resolved)
    cf = {str(r["instance_id"]): changed_file_count(str(r.get("patch") or "")) for r in rows}
    multi = sorted(i for i in resolved if cf.get(i, 0) >= 2)
    single = sorted(i for i in resolved if cf.get(i, 0) == 1)
    print(f"multi-file (>=2): {len(multi)}   single-file: {len(single)}")
    (out.parent / "opus45_verified_resolved_multifile.txt").write_text("\n".join(multi) + "\n", encoding="utf-8")
    by_repo_multi = collections.Counter(repo_of(i) for i in multi)
    print("multi-file by repo:", dict(by_repo_multi.most_common()))


if __name__ == "__main__":
    main()
