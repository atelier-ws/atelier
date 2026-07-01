"""How many def-gold-dropped queries have a LEGIT unambiguous definition match?

A dropped query is a safe reintroduction candidate if it names a symbol defined
in exactly ONE file (unambiguous) -- a high-confidence gold even if the purity
gate dropped it for mixing the symbol with regex/content tokens.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, "benchmarks/codebench")
from build_definition_gold import _idents, _symbol_def_index

m = json.load(open("benchmarks/codebench/data/bench_pairs_swebench_gold.json"))
g = json.load(open("benchmarks/codebench/data/bench_pairs_def_gold.json"))
guq = {(p[2], p[0]) for p in g["pairs"]}

dropped: dict[str, list[str]] = defaultdict(list)
seen: set[tuple[str, str]] = set()
for q, _tid, prefix in m["pairs"]:
    if (prefix, q) in seen:
        continue
    seen.add((prefix, q))
    if (prefix, q) not in guq:
        dropped[prefix].append(q)

repos = m["repos"]
total = 0
legit = 0
examples: list[tuple[str, str, list[str]]] = []
for prefix, queries in dropped.items():
    db = repos.get(prefix, {}).get("db")
    if not db or not os.path.exists(db):
        continue
    sym2files = _symbol_def_index(db)
    for q in queries:
        total += 1
        gold: set[str] = set()
        for w in {t.lower() for t in _idents(q) if len(t) >= 4}:
            files = sym2files.get(w)
            if files and len(files) == 1:
                gold |= files
        if gold:
            legit += 1
            if len(examples) < 22:
                examples.append((prefix, q, sorted(gold)[:2]))

print(f"dropped queries checked: {total}")
print(f"  with an UNAMBIGUOUS symbol definition (legit reintroduction): {legit} ({100 * legit / max(total, 1):.0f}%)")
print("\nexamples (would be reintroduced):")
for prefix, q, gold in examples:
    print(f"  [{prefix.split('__')[-1]:<10}] {q[:55]!r}")
    print(f"       -> {', '.join(gold)}")
