"""Is the atelier golden set flawed for RETRIEVAL, i.e. why can't MRR reach ~1.0?

The bench gold = the file(s) edited in the SWE-task fix (edit-localization). A query
mined from that task names some symbols. We check, per query, whether the gold file
actually DEFINES a symbol the query names:
  * non-symbolic     : the query names no known symbol (prose/path tokens)
  * gold-defines     : a gold file defines a query symbol  (retrieval-fair)
  * gold-elsewhere   : query symbols are DEFINED in non-gold files (gold is an
                       edit/usage site, not where you'd 'search' to) -- a label that
                       a definition-retriever structurally cannot score, however good.
Reports the share of each, gold-is-test rate, lexical MRR per category, and the
'fair-subset' lexical MRR (the ceiling when the gold is actually findable).
"""

from __future__ import annotations

import json
import re
import signal
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine

KW = {
    "def",
    "class",
    "async",
    "return",
    "self",
    "import",
    "from",
    "none",
    "true",
    "false",
    "if",
    "else",
    "for",
    "while",
    "and",
    "or",
    "not",
    "with",
    "try",
    "except",
    "the",
    "path",
}


def norm(p):
    return (p or "").replace("\\", "/")


def idents(q):
    return [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", q) if t.lower() not in KW]


def rank_true(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None


def _alarm(s, f):
    raise TimeoutError


def main() -> int:
    d = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
    meta = d["repos"]["atelier__atelier"]
    tm = d["true_map"]
    pairs = [(q, t) for q, t, p in d["pairs"] if p == "atelier__atelier"]
    eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)
    eng._cache_set = lambda *a, **k: None
    eng._schema_ready = True

    c = sqlite3.connect(f"file:{meta['db']}?mode=ro", uri=True)
    sym2files: dict[str, set[str]] = {}
    for name, fp in c.execute("SELECT symbol_name, file_path FROM symbols WHERE repo_id=?", (eng.repo_id,)):
        if name:
            sym2files.setdefault(name.lower(), set()).add(norm(fp))
    c.close()

    def def_files(q):
        out = set()
        for t in idents(q):
            out |= sym2files.get(t.lower(), set())
        return out

    cats = {"non-symbolic": 0, "gold-defines": 0, "gold-elsewhere": 0}
    test_gold = 0
    # MRR accumulators per category, plus overall
    mrr = {k: [0.0, 0] for k in list(cats) + ["ALL", "fair(gold-defines)"]}
    miss_cats = {k: 0 for k in cats}
    examples = []
    for q, tid in pairs:
        trues = [norm(t) for t in (tm.get(tid) or [])]
        if not trues:
            continue
        dfs = def_files(q)
        gold_def = any(any(t.endswith(f) or f.endswith(t) for t in trues) for f in dfs)
        if not dfs:
            cat = "non-symbolic"
        elif gold_def:
            cat = "gold-defines"
        else:
            cat = "gold-elsewhere"
        cats[cat] += 1
        if any("test" in t for t in trues):
            test_gold += 1
        prev = signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, 5.0)
        lexf = []
        try:
            r = eng.tool_explore(q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
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
        rk = rank_true(lexf, trues)
        rr = 1.0 / rk if rk else 0.0
        for key in (cat, "ALL"):
            mrr[key][0] += rr
            mrr[key][1] += 1
        if cat == "gold-defines":
            mrr["fair(gold-defines)"][0] += rr
            mrr["fair(gold-defines)"][1] += 1
        if not rk:
            miss_cats[cat] += 1
            if cat == "gold-elsewhere" and len(examples) < 8:
                examples.append((q[:55], list(dfs)[:1], trues[:1]))

    n = sum(cats.values())
    print(f"\n=== atelier gold-quality for retrieval (n={n}) ===")
    print(f"  gold is a TEST file: {test_gold} ({100 * test_gold / n:.0f}%)")
    print("\n  category            share     lexMRR   (what it means)")
    desc = {
        "gold-defines": "gold defines a query symbol (fair)",
        "gold-elsewhere": "query symbol defined in a NON-gold file",
        "non-symbolic": "query names no known symbol",
    }
    for k in ("gold-defines", "gold-elsewhere", "non-symbolic"):
        m = mrr[k][0] / max(mrr[k][1], 1)
        print(f"  {k:16s}  {100 * cats[k] / n:4.0f}%   {m:.3f}    {desc[k]}")
    print(f"\n  OVERALL lexical MRR        = {mrr['ALL'][0] / max(mrr['ALL'][1], 1):.3f}  (n={mrr['ALL'][1]})")
    print(
        f"  FAIR-SUBSET lexical MRR    = {mrr['fair(gold-defines)'][0] / max(mrr['fair(gold-defines)'][1], 1):.3f}"
        f"  (only queries whose gold defines a named symbol, n={mrr['fair(gold-defines)'][1]})"
    )
    tot_miss = sum(miss_cats.values())
    print(f"\n  of {tot_miss} total misses (gold not in lexical top-10):")
    for k in ("gold-elsewhere", "non-symbolic", "gold-defines"):
        print(f"    {k:16s} {miss_cats[k]:4d} ({100 * miss_cats[k] / max(tot_miss, 1):.0f}%)")
    print("\n  sample 'gold-elsewhere' misses (query | where its symbol is defined | the gold):")
    for q, dfs, trues in examples:
        print(f"    {q!r}")
        print(f"        defined in: {dfs}   gold: {trues}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
