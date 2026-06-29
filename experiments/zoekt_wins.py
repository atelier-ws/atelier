"""Per-query A/B: where does zoekt change the rank of the true file vs pure lexical?

For each sampled query we run tool_explore twice in one process:
  A) lexical only  -- _zoekt_candidate_files stubbed to []
  B) lexical+zoekt -- real zoekt
and compare the reciprocal rank of the gold file. Then we characterise the
queries where zoekt helps most.
"""

import collections
import json
import os
import random
import re

os.environ["FITNESS_LEAN"] = "1"
os.environ["ATELIER_ZOEKT_MODE"] = "auto"
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

DATA = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
repos = DATA["repos"]
pairs = DATA["pairs"]
true_map = DATA["true_map"]

by_prefix = collections.defaultdict(list)
for q, tid, prefix in pairs:
    by_prefix[prefix].append((q, tid))


def norm(p):
    return p.replace("\\", "/").lstrip("./").lower()


def rank_true(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None


SAMPLE = int(os.environ.get("WINS_SAMPLE", "40"))
rnd = random.Random(13)

engines = {}
for prefix, meta in repos.items():
    eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)
    eng._cache_set = lambda *a, **k: None
    eng._schema_ready = True
    engines[prefix] = eng
    with __import__("contextlib").suppress(Exception):
        eng._symbol_centrality_map()
    try:
        get_zoekt_supervisor(eng.repo_root).server.wait_until_searchable(30.0)
    except Exception:  # noqa: BLE001
        pass

EMPTY = []
rows = []
for prefix, eng in engines.items():
    qs = by_prefix.get(prefix) or []
    rnd.shuffle(qs)
    for q, tid in qs[:SAMPLE]:
        trues = true_map.get(tid)
        if not trues:
            continue
        real = eng._zoekt_candidate_files
        # Pass A: lexical only
        eng._zoekt_candidate_files = lambda *a, **k: list(EMPTY)
        try:
            ra = eng.tool_explore(q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
            fa = [f.get("path", "") for f in ra.get("files", [])]
        except Exception:  # noqa: BLE001
            fa = []
        eng._zoekt_candidate_files = real
        # Pass B: lexical+zoekt
        try:
            rb = eng.tool_explore(q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
            fb = [f.get("path", "") for f in rb.get("files", [])]
        except Exception:  # noqa: BLE001
            fb = []
        rka = rank_true(fa, trues)
        rkb = rank_true(fb, trues)
        rr = (1.0 / rkb if rkb else 0.0) - (1.0 / rka if rka else 0.0)
        rows.append((rr, prefix, q, rka, rkb))

n = len(rows)
wins = [r for r in rows if r[0] > 0.001]
losses = [r for r in rows if r[0] < -0.001]
print(f"=== {n} queries  |  zoekt helped {len(wins)}  hurt {len(losses)}  neutral {n - len(wins) - len(losses)} ===")
print(f"mean RR delta from zoekt: {sum(r[0] for r in rows) / max(n, 1):+.4f}")


def feat(q):
    f = []
    if "|" in q:
        f.append("alt|")
    if ".*" in q or ".+" in q:
        f.append("wildcard.*")
    if re.search(r"[\\()\[\]{}^$]", q):
        f.append("regexmeta")
    if " " in q.strip():
        f.append("multiword")
    if re.search(r"[a-z]_[a-z]", q) or any(c.isupper() for c in q[1:]):
        f.append("compound_id")
    if "=" in q or "(" in q:
        f.append("codeliteral")
    return ",".join(f) or "plainword"


print("\n=== TOP zoekt WINS (lexical rank -> zoekt rank) ===")
for rr, prefix, q, rka, rkb in sorted(wins, reverse=True)[:18]:
    print(
        f"  +{rr:.3f}  {('miss' if rka is None else rka):>4} -> {rkb:<3}  [{feat(q)}]  {prefix.split('__')[-1]:<12} {q[:48]!r}"
    )

print("\n=== zoekt feature tally among wins ===")
fc = collections.Counter()
for rr, prefix, q, rka, rkb in wins:
    fc[feat(q)] += 1
for k, v in fc.most_common():
    print(f"  {v:>3}  {k}")

print("\n=== TOP zoekt LOSSES ===")
for rr, prefix, q, rka, rkb in sorted(losses)[:8]:
    print(
        f"  {rr:.3f}  {('miss' if rka is None else rka):>4} -> {('miss' if rkb is None else rkb)}  [{feat(q)}]  {prefix.split('__')[-1]:<12} {q[:48]!r}"
    )
