"""One-off: restore full repos dict in semantic gold from def gold, then rebalance."""

import json
from pathlib import Path

DATA = Path("benchmarks/codebench/data")

# 1. Pull full repos dict from def gold
def_d = json.loads((DATA / "bench_pairs_def_gold.json").read_text())
full_repos = def_d["repos"]

# 2. Restore into semantic gold
sem_path = DATA / "bench_pairs_semantic_gold.json"
sem_d = json.loads(sem_path.read_text())
sem_d["repos"] = full_repos
sem_path.write_text(json.dumps(sem_d, indent=2))
print(f"Fixed: semantic gold now has {len(full_repos)} repos in metadata")
print("Repos:", list(full_repos.keys()))
