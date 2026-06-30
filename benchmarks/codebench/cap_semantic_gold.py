"""Cap semantic gold to target per repo for balanced eval."""

import json
import random
from collections import defaultdict
from pathlib import Path

TARGET = 40
rng = random.Random(42)
p = Path("benchmarks/codebench/data/bench_pairs_semantic_gold.json")
d = json.loads(p.read_text())
pairs, true_map, repos = d["pairs"], d["true_map"], d["repos"]

by_repo = defaultdict(list)
for pair in pairs:
    by_repo[pair[2]].append(pair)

new_pairs, new_true_map = [], {}
for repo, rpairs in sorted(by_repo.items()):
    sampled = rng.sample(rpairs, min(len(rpairs), TARGET))
    new_pairs.extend(sampled)
    for _, tid, _ in sampled:
        if tid in true_map:
            new_true_map[tid] = true_map[tid]
    arrow = "->" if len(rpairs) != len(sampled) else "  "
    print(f"  {len(rpairs):>4} {arrow} {len(sampled):>3}  {repo.split('__')[-1]}")

print(f"Total: {len(pairs)} -> {len(new_pairs)}")
d2 = {**d, "pairs": new_pairs, "true_map": new_true_map}
p.write_text(json.dumps(d2, indent=2))
print(f"Saved -> {p}")
