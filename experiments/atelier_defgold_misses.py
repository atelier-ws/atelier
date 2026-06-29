"""Why is atelier low (0.72) on the DEFINITION gold when other repos are 0.93-1.0?

Runs tool_explore deep (top-30) on each atelier def-gold query and classifies the
outcome: hit@1/@3/@10, just-outside (rank 11-30 = a ranking problem), or absent
(>30 / gold not even in the index = stale/derivation problem). Buckets by query
shape and prints worst-case examples with what lexical returned instead.
"""

from __future__ import annotations

import json
import signal
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "src")
import os

from atelier.core.capabilities.code_context.engine import CodeContextEngine

GOLD = os.environ.get("DEF_GOLD", "benchmarks/codebench/data/bench_pairs_def_gold.json")


def norm(p):
    return (p or "").replace("\\", "/")


def shape(q):
    if "|" in q:
        return "alternation"
    if " " not in q.strip():
        return "single-token"
    return "multiword"


def rank_in(files, trues):
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) or t.endswith(norm(f)) for t in trues):
            return i
    return None


def _alarm(s, f):
    raise TimeoutError


def main() -> int:
    d = json.load(open(GOLD))
    tm = d["true_map"]
    meta = d["repos"]["atelier__atelier"]
    pairs = [(q, t) for q, t, p in d["pairs"] if p == "atelier__atelier"]
    eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)
    eng._cache_set = lambda *a, **k: None
    eng._schema_ready = True

    # which gold files even exist in the current index?
    c = sqlite3.connect(f"file:{meta['db']}?mode=ro", uri=True)
    idx_files = {norm(r[0]) for r in c.execute("SELECT DISTINCT file_path FROM symbols")}
    c.close()

    cats = {"hit@1": 0, "hit@3": 0, "hit@10": 0, "outside(11-30)": 0, "absent(>30)": 0}
    by_shape = {}
    gold_not_indexed = 0
    rr_sum = 0.0
    examples = []
    for q, tid in pairs:
        trues = [norm(t) for t in (tm.get(tid) or [])]
        if not trues:
            continue
        if not any(any(f.endswith(t) or t.endswith(f) for f in idx_files) for t in trues):
            gold_not_indexed += 1
        prev = signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, 6.0)
        lexf = []
        try:
            r = eng.tool_explore(q, max_files=30, auto_index=False, include_source=False, include_relationships=False)
            seen = set()
            for f in (x.get("path", "") for x in r.get("files", [])):
                f = norm(f)
                if f and f not in seen:
                    seen.add(f)
                    lexf.append(f)
        except Exception:  # noqa: BLE001
            lexf = []
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, prev)
        rk = rank_in(lexf, trues)
        rr_sum += 1.0 / rk if (rk and rk <= 10) else 0.0
        sh = shape(q)
        bs = by_shape.setdefault(sh, {"n": 0, "rr": 0.0})
        bs["n"] += 1
        bs["rr"] += 1.0 / rk if (rk and rk <= 10) else 0.0
        if rk == 1:
            cats["hit@1"] += 1
        elif rk and rk <= 3:
            cats["hit@3"] += 1
        elif rk and rk <= 10:
            cats["hit@10"] += 1
        elif rk and rk <= 30:
            cats["outside(11-30)"] += 1
            if len(examples) < 10:
                examples.append((sh, rk, q[:48], trues[:1], lexf[:3]))
        else:
            cats["absent(>30)"] += 1
            if len(examples) < 10:
                examples.append((sh, None, q[:48], trues[:1], lexf[:3]))

    n = sum(cats.values())
    print(f"\n=== atelier definition-gold miss analysis (n={n}) ===")
    print(
        f"  MRR@10 = {rr_sum / max(n, 1):.3f}   gold-not-in-index: {gold_not_indexed} ({100 * gold_not_indexed / max(n, 1):.0f}%)"
    )
    print("  outcome distribution:")
    for k, v in cats.items():
        print(f"    {k:16s} {v:4d}  ({100 * v / max(n, 1):.0f}%)")
    print("  by shape (MRR@10):")
    for sh, v in sorted(by_shape.items(), key=lambda kv: -kv[1]["n"]):
        print(f"    {sh:14s} n={v['n']:4d}  MRR={v['rr'] / max(v['n'], 1):.3f}")
    print("\n  worst examples (shape | deep-rank | query | gold | lexical top-3):")
    for sh, rk, q, g, top in examples:
        print(f"    [{sh:11s} rk={rk}] {q!r}")
        print(f"        gold={[x.split('/')[-1] for x in g]}  got={[x.split('/')[-1] for x in top]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
