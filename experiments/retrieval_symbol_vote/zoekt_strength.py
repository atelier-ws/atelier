"""Find queries where Zoekt rescues a result lexical-only misses (zoekt's strength).

For each bench query, rank the gold file under:
  - lexical-only   (ATELIER_ZOEKT_MODE=off)
  - lexical+zoekt  (ATELIER_ZOEKT_MODE=installed, gate OFF => full broad zoekt)
Then bucket: RESCUE (lexical worse/missed, zoekt better) vs HURT (reverse).

Single process, toggles zoekt per call (cache stubbed). Run:
  PYTHONPATH=src uv run python experiments/retrieval_symbol_vote/zoekt_strength.py --per-repo 40
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")

from atelier.core.capabilities.code_context.engine import CodeContextEngine

try:
    from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor
except Exception:  # noqa: BLE001
    get_zoekt_supervisor = None


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def _rank(files: list[str], golds: list[str]) -> int | None:
    gn = [_norm(g) for g in golds]
    for i, f in enumerate(files, 1):
        if any(_norm(f).endswith(g) for g in gn):
            return i
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-repo", type=int, default=40)
    ap.add_argument("--depth", type=int, default=10)
    ap.add_argument("--repo", default="")
    args = ap.parse_args()

    data = json.load(open(os.environ.get("FITNESS_PAIRS", "benchmarks/codebench/data/bench_pairs_multi.json")))
    pairs, true_map, repos = data["pairs"], data["true_map"], data["repos"]

    engines: dict[str, CodeContextEngine] = {}
    for prefix, meta in repos.items():
        if args.repo and args.repo not in prefix:
            continue
        db = Path(meta["db"]) if meta.get("db") else None
        e = CodeContextEngine(Path(meta["ws"]), db_path=db, autosync_enabled=False)
        e._cache_get = lambda *a, **k: (False, None)
        e._cache_set = lambda *a, **k: None
        e._schema_ready = True
        if get_zoekt_supervisor is not None:
            with contextlib.suppress(Exception):
                get_zoekt_supervisor(Path(meta["ws"]))
        engines[prefix] = e
    if get_zoekt_supervisor is not None:
        for prefix in list(engines):
            with contextlib.suppress(Exception):
                get_zoekt_supervisor(engines[prefix].repo_root).server.wait_until_searchable(30.0)

    by_repo: dict[str, list[tuple[str, str]]] = {}
    for q, tid, prefix in pairs:
        if prefix in engines:
            by_repo.setdefault(prefix, []).append((q, tid))

    def explore(engine: CodeContextEngine, query: str, *, zoekt: bool) -> list[str]:
        if zoekt:
            os.environ["ATELIER_ZOEKT_MODE"] = "installed"
            os.environ["ATELIER_ZOEKT_GATE"] = "0"
        else:
            os.environ["ATELIER_ZOEKT_MODE"] = "off"
        try:
            payload = engine.tool_explore(query, max_files=args.depth, auto_index=False)
            return [_norm(f.get("path", "")) for f in payload.get("files", [])]
        except Exception:  # noqa: BLE001
            return []

    rescue: list[tuple[str, str, list[str], int | None, int | None]] = []
    hurt: list[tuple[str, str, list[str], int | None, int | None]] = []
    total = 0
    rr_lex = rr_zk = 0.0
    h1_lex = h1_zk = h10_lex = h10_zk = 0
    for prefix, items in by_repo.items():
        engine = engines[prefix]
        seen: set[str] = set()
        sampled: list[tuple[str, str]] = []
        for q, tid in sorted(items):
            if q in seen:
                continue
            seen.add(q)
            sampled.append((q, tid))
            if len(sampled) >= args.per_repo:
                break
        for q, tid in sampled:
            golds = true_map.get(tid) or []
            if not golds:
                continue
            rl = _rank(explore(engine, q, zoekt=False), golds)
            rz = _rank(explore(engine, q, zoekt=True), golds)
            total += 1
            rr_lex += (1.0 / rl) if rl else 0.0
            rr_zk += (1.0 / rz) if rz else 0.0
            h1_lex += int(rl == 1)
            h1_zk += int(rz == 1)
            h10_lex += int(rl is not None)
            h10_zk += int(rz is not None)
            lk = rl if rl is not None else 999
            zk = rz if rz is not None else 999
            if zk < lk:
                rescue.append((prefix, q, golds, rl, rz))
            elif zk > lk:
                hurt.append((prefix, q, golds, rl, rz))

    n = max(total, 1)
    print(f"\nqueries={total}")
    print(f"  lexical-only : MRR={rr_lex / n:.4f}  hit@1={h1_lex / n:.4f}  recall@10={h10_lex / n:.4f}")
    print(f"  +full zoekt  : MRR={rr_zk / n:.4f}  hit@1={h1_zk / n:.4f}  recall@10={h10_zk / n:.4f}")
    print(f"  delta        : MRR={(rr_zk - rr_lex) / n:+.4f}  hit@1={(h1_zk - h1_lex) / n:+.4f}  recall@10={(h10_zk - h10_lex) / n:+.4f}")
    print(f"  win/loss count: RESCUE={len(rescue)}  HURT={len(hurt)}  net={len(rescue) - len(hurt)}")
    print("\n=== ZOEKT STRENGTH (lexical missed/worse -> zoekt better) ===")
    for prefix, q, golds, rl, rz in sorted(rescue, key=lambda x: (x[3] or 999) - (x[4] or 999))[:20]:
        print(f"  [{prefix.split('__')[-1]:<10}] lex_rank={rl} zoekt_rank={rz}  q={q!r}")
        print(f"      gold: {', '.join(golds[:3])}")
    print("\n=== ZOEKT HURT (lexical better -> zoekt worse) ===")
    for prefix, q, golds, rl, rz in hurt[:8]:
        print(f"  [{prefix.split('__')[-1]:<10}] lex_rank={rl} zoekt_rank={rz}  q={q!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
