"""Merge session + synthetic pair JSONs into a single training corpus."""

from __future__ import annotations

import json
import sys


def merge(paths: list[str], out: str) -> None:
    merged_pairs: list = []
    merged_map: dict = {}
    merged_repos: dict = {}
    for p in paths:
        with open(p) as f:
            d = json.load(f)
        merged_pairs.extend(d["pairs"])
        for k, v in d["true_map"].items():
            if k not in merged_map:
                merged_map[k] = v
            else:
                # union gold files
                existing = set(merged_map[k])
                merged_map[k] = list(existing | set(v))
        merged_repos.update(d.get("repos", {}))
    result = {"pairs": merged_pairs, "true_map": merged_map, "repos": merged_repos}
    with open(out, "w") as f:
        json.dump(result, f)
    print(
        f"[merge] {len(merged_pairs)} pairs, {len(merged_map)} tids, {len(merged_repos)} repos → {out}", file=sys.stderr
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    merge(args.inputs, args.out)
