"""Cross-repo lexical MRR@10 on the (purity-gated) definition gold.

No semantic model load -- just tool_explore per query, ranked vs the def gold.
Confirms the purity gate left every repo at/above its prior number and that
atelier is no longer the outlier. Point at a gold with DEF_GOLD=...
"""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine

GOLD = os.environ.get("DEF_GOLD", "benchmarks/codebench/data/bench_pairs_def_gold.json")


def norm(p):
    return (p or "").replace("\\", "/")


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
    repos = d["repos"]
    by_repo: dict[str, list] = {}
    for q, tid, prefix in d["pairs"]:
        by_repo.setdefault(prefix, []).append((q, tid))

    signal.signal(signal.SIGALRM, _alarm)
    print(f"{'repo':28s} {'n':>5} {'MRR@10':>8} {'hit@1':>6}")
    g_rr = g_n = 0.0
    rows = []
    for prefix, pairs in sorted(by_repo.items()):
        meta = repos.get(prefix, {})
        db = meta.get("db")
        if not db or not Path(db).is_file():
            continue
        eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(db), autosync_enabled=False)
        eng._cache_get = lambda *a, **k: (False, None)
        eng._cache_set = lambda *a, **k: None
        eng._schema_ready = True
        rr = h1 = n = 0.0
        for q, tid in pairs:
            trues = [norm(t) for t in (tm.get(tid) or [])]
            if not trues:
                continue
            n += 1
            signal.setitimer(signal.ITIMER_REAL, 6.0)
            lexf = []
            try:
                r = eng.tool_explore(
                    q, max_files=10, auto_index=False, include_source=False, include_relationships=False
                )
                seen = set()
                for f in (x.get("path", "") for x in r.get("files", [])):
                    f = norm(f)
                    if f and f not in seen:
                        seen.add(f)
                        lexf.append(f)
            except Exception:
                lexf = []
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
            rk = rank_in(lexf, trues)
            if rk and rk <= 10:
                rr += 1.0 / rk
            if rk == 1:
                h1 += 1
        rows.append((prefix, n, rr / max(n, 1), h1 / max(n, 1)))
        g_rr += rr
        g_n += n
    for prefix, n, mrr, h1 in rows:
        print(f"{prefix:28s} {int(n):5d} {mrr:8.3f} {h1:6.2f}")
    print(f"{'OVERALL':28s} {int(g_n):5d} {g_rr / max(g_n, 1):8.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
