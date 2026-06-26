"""Augment bench_pairs_multi.json with symbol-name queries extracted directly
from the gold files in true_map.

For every (tid, gold_files) entry we parse each gold .py file with the AST and
extract top-level and class-level function/class/constant names, then emit a
new pair [name, tid, prefix].  This is valid: a developer searching for a
function by name SHOULD find the file that defines it.

Filters:
  - name length 4-60
  - skip dunder names
  - skip names already present as a query for the same (tid, prefix)

Usage:
  uv run python scripts/_augment_pairs.py
"""

import ast
import json
import os
import pathlib
import sys

OUT = pathlib.Path("/tmp/bench_pairs_multi.json")


def _extract_names(path: pathlib.Path) -> list[str]:
    """Return top-level and class-body symbol names from a Python source file.

    Intentionally shallow: module body + class bodies only, NOT function
    internals.  This avoids local variable names that are too generic.
    Names must be >= 8 chars and not look like a dunder or test helper.
    """
    try:
        tree = ast.parse(path.read_bytes())
    except Exception:  # noqa: BLE001
        return []
    names: list[str] = []

    def _accept(name: str) -> bool:
        if len(name) < 8:
            return False
        if name.startswith("__") and name.endswith("__"):
            return False
        return True

    def _scan(stmts: list[ast.stmt]) -> None:
        for node in stmts:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if _accept(node.name):
                    names.append(node.name)
                if isinstance(node, ast.ClassDef):
                    _scan(node.body)  # one level deep into classes
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and _accept(t.id):
                        names.append(t.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if _accept(node.target.id):
                    names.append(node.target.id)

    _scan(tree.body)
    return names


def main() -> None:
    data = json.loads(OUT.read_text())
    pairs: list[list[str]] = data["pairs"]
    true_map: dict[str, list[str]] = data["true_map"]
    repos: dict[str, dict] = data["repos"]

    # Build per-(prefix, tid) set of existing queries to avoid duplication
    # true_map keys don't carry prefix, so map tid to prefix via pairs
    tid_prefix: dict[str, str] = {tid: prefix for _, tid, prefix in pairs}
    existing: dict[tuple[str, str], set[str]] = {}
    for q, tid, prefix in pairs:
        existing.setdefault((prefix, tid), set()).add(q.lower())

    # How many synthetic pairs do we need to reach ~TARGET total?
    TARGET = int(os.environ.get("AUGMENT_TARGET", "1200"))
    budget = max(0, TARGET - len(pairs))

    new_pairs: list[list[str]] = []
    skipped_missing = 0

    for tid, gold_files in true_map.items():
        if len(new_pairs) >= budget:
            break
        prefix = tid_prefix.get(tid, "")
        if not prefix:
            continue
        ws = pathlib.Path(repos[prefix]["ws"])
        ex = existing.get((prefix, tid), set())
        for rel in gold_files:
            if len(new_pairs) >= budget:
                break
            full = ws / rel
            if not full.exists() or not rel.endswith(".py"):
                skipped_missing += 1
                continue
            for name in _extract_names(full):
                if len(new_pairs) >= budget:
                    break
                if len(name) < 4 or len(name) > 60:
                    continue
                if name.startswith("__") and name.endswith("__"):
                    continue
                if name.lower() in ex:
                    continue
                new_pairs.append([name, tid, prefix])
                ex.add(name.lower())

    print(
        f"[augment] +{len(new_pairs)} synthetic pairs (target {TARGET}, budget was {budget}, skipped {skipped_missing} missing/non-py)",
        flush=True,
    )
    merged = pairs + new_pairs
    uniq = len({(q, p) for q, _, p in merged})
    print(f"[augment] total: {len(merged)} pairs | {uniq} unique (query,repo)", flush=True)
    data["pairs"] = merged
    OUT.write_text(json.dumps(data))
    print(f"[augment] wrote {OUT}", flush=True)


if __name__ == "__main__":
    sys.path.insert(0, "src")
    main()
