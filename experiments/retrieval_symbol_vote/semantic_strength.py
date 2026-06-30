"""Mine queries where lexical+zoekt fails but semantic search rescues them.

For each benchmark query, runs three arms:
  - lex:     tool_explore with ATELIER_ZOEKT_MODE=off   (pure lexical FTS)
  - lex+zk:  tool_explore with ATELIER_ZOEKT_MODE=installed (lexical + Zoekt)
  - semantic: cosine over symbol embeddings (BGE or Nomic via ATELIER_CODE_EMBEDDER)

Buckets:
  RESCUE  -- lex+zk misses (rank>depth or None), semantic finds (rank<=depth)
  HURT    -- semantic misses, lex+zk finds
  BOTH    -- both find (control positives)
  NEITHER -- both miss

Outputs:
  1. Console summary: bucket counts, sample rescued queries, delta-MRR
  2. benchmarks/codebench/data/bench_pairs_semantic_gold.json -- rescued pairs
     in the same format as bench_pairs_def_gold.json, ready for the MRR harness.

Usage:
    # Nomic (matches codebase-memory-mcp's bundled model)
    ATELIER_CODE_EMBEDDER=nomic ATELIER_NOMIC_DIM=768 \
        uv run python experiments/retrieval_symbol_vote/semantic_strength.py

    # BGE-Code-v1 (Atelier's existing embedder)
    ATELIER_CODE_EMBEDDER=bge \
        uv run python experiments/retrieval_symbol_vote/semantic_strength.py

    # limit repos / queries for a quick run
    FITNESS_REPO=django FITNESS_SAMPLE=50 ATELIER_CODE_EMBEDDER=nomic \
        uv run python experiments/retrieval_symbol_vote/semantic_strength.py
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.core.foundation.paths import workspace_key
from atelier.infra.embeddings.factory import make_code_embedder

try:
    from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor
except Exception:  # noqa: BLE001
    get_zoekt_supervisor = None

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
ap = argparse.ArgumentParser(description="Mine queries where semantic rescues lexical+zoekt")
ap.add_argument("--per-repo", type=int, default=0, help="Max queries per repo (0 = all)")
ap.add_argument("--depth", type=int, default=10, help="Rank cutoff for hit/miss")
ap.add_argument("--repo", default=os.environ.get("FITNESS_REPO", ""), help="Filter by repo substring")
ap.add_argument(
    "--gold",
    default=os.environ.get(
        "FITNESS_PAIRS",
        "benchmarks/codebench/data/bench_pairs_def_gold.json,benchmarks/codebench/data/bench_pairs_content_gold.json",
    ),
    help="Comma-separated gold JSON paths",
)
ap.add_argument(
    "--out",
    default="benchmarks/codebench/data/bench_pairs_semantic_gold.json",
    help="Output gold file for rescued pairs",
)
ap.add_argument("--timeout", type=float, default=5.0, help="Per-query explore timeout (s)")
args = ap.parse_args()

PER_REPO = args.per_repo or int(os.environ.get("FITNESS_SAMPLE", "0"))
DEPTH = args.depth
TIMEOUT = args.timeout
# Capture the embedder pin NOW, then scrub it from the environment so that
# CodeContextEngine instances (one per repo) don't each try to load the model
# inside their SemanticSearchRanker on first tool_explore call.
EMBEDDER_PIN = os.environ.get("ATELIER_CODE_EMBEDDER", "nomic")
for _k in ("ATELIER_CODE_EMBEDDER", "ATELIER_NOMIC_DIM", "ATELIER_BGE_MAX_SEQ"):
    os.environ.pop(_k, None)

# ---------------------------------------------------------------------------
# Load gold pairs
# ---------------------------------------------------------------------------
golds: list[tuple[str, list, dict]] = []
repos: dict | None = None
for gp in args.gold.split(","):
    gp = gp.strip()
    if not gp:
        continue
    with open(gp) as f:
        d = json.load(f)
    if repos is None:
        repos = d["repos"]
    golds.append((d.get("gold_kind", "definition"), d["pairs"], d["true_map"]))
assert repos is not None

pairs_all = [r for _, p, _ in golds for r in p]

uq: dict[str, list[str]] = {}
for q, _, prefix in pairs_all:
    if q not in uq.setdefault(prefix, []):
        uq[prefix].append(q)

if args.repo:
    uq = {p: qs for p, qs in uq.items() if args.repo in p}
if PER_REPO:
    uq = {p: sorted(qs)[:PER_REPO] for p, qs in uq.items()}

total_queries = sum(len(qs) for qs in uq.values())
print(f"[mine] embedder={EMBEDDER_PIN} repos={len(uq)} queries={total_queries}", flush=True)

# ---------------------------------------------------------------------------
# Build engines (lexical+zoekt arm)
# ---------------------------------------------------------------------------
engines: dict[str, CodeContextEngine] = {}
for prefix, meta in repos.items():
    if prefix not in uq:
        continue
    db_path: Path | None = None
    if meta.get("db"):
        db_path = Path(meta["db"])
    else:
        db_path = Path("/tmp") / workspace_key(Path(meta["ws"]).resolve()) / "code_context.sqlite"
    if not Path(meta["ws"]).is_dir():
        print(f"[skip] {prefix}: workspace not found", flush=True)
        continue
    eng = CodeContextEngine(Path(meta["ws"]), db_path=db_path, autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)  # type: ignore[method-assign]
    eng._cache_set = lambda *a, **k: None  # type: ignore[method-assign]
    eng._schema_ready = True
    if get_zoekt_supervisor is not None:
        with contextlib.suppress(Exception):
            get_zoekt_supervisor(Path(meta["ws"]))
    engines[prefix] = eng

# warm Zoekt servers
if get_zoekt_supervisor is not None:
    for eng in engines.values():
        with contextlib.suppress(Exception):
            get_zoekt_supervisor(eng.repo_root).server.wait_until_searchable(20.0)

# ---------------------------------------------------------------------------
# Load embedder + build per-repo symbol vectors
# ---------------------------------------------------------------------------
embedder = make_code_embedder(pin=EMBEDDER_PIN)
print(f"[mine] embedder loaded: {embedder.name} dim={embedder.dim}", flush=True)


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# symbol vectors per repo: {prefix: (doc_mat np.ndarray, doc_paths)}
repo_vecs: dict[str, tuple[np.ndarray, list[str]]] = {}
for prefix, eng in engines.items():
    candidate = (
        Path(repos[prefix]["db"]) if repos[prefix].get("db") else
        Path("/tmp") / workspace_key(Path(repos[prefix]["ws"]).resolve()) / "code_context.sqlite"
    )
    if not candidate.exists():
        print(f"[skip-sem] {prefix}: DB not found at {candidate}", flush=True)
        continue
    con = sqlite3.connect(str(candidate))
    rows = con.execute(
        "SELECT file_path, symbol_name, kind, doc_summary FROM symbols "
        "WHERE file_path IS NOT NULL LIMIT 100000"
    ).fetchall()
    con.close()
    if not rows:
        print(f"[skip-sem] {prefix}: no symbols", flush=True)
        continue
    doc_texts = [f"{r[1]} {r[2]} {r[3] or ''}".strip() for r in rows]
    doc_paths = [_norm(r[0]) for r in rows]
    t0 = time.time()
    doc_mat = np.array(embedder.embed_documents(doc_texts), dtype=np.float32)
    print(f"[mine] {prefix}: {len(doc_texts)} symbols embedded in {time.time()-t0:.1f}s", flush=True)
    repo_vecs[prefix] = (doc_mat, doc_paths)


# ---------------------------------------------------------------------------
# Per-query: run lex+zk arm and semantic arm
# ---------------------------------------------------------------------------
def _explore(eng: CodeContextEngine, query: str, *, zoekt: bool) -> list[str]:
    if zoekt:
        os.environ["ATELIER_ZOEKT_MODE"] = "installed"
        os.environ.pop("ATELIER_ZOEKT_GATE", None)
    else:
        os.environ["ATELIER_ZOEKT_MODE"] = "off"
    try:
        payload = eng.tool_explore(query, max_files=DEPTH, auto_index=False)
        return [_norm(f.get("path", "")) for f in payload.get("files", [])]
    except Exception:  # noqa: BLE001
        return []


def _semantic_batch(prefix: str, queries: list[str]) -> dict[str, list[str]]:
    """Embed all queries at once, rank via matmul. Much faster than one-by-one."""
    if prefix not in repo_vecs:
        return {q: [] for q in queries}
    doc_mat, doc_paths = repo_vecs[prefix]
    q_mat = np.array(embedder.embed_queries(queries), dtype=np.float32)  # (Q, dim)
    sim = q_mat @ doc_mat.T                                               # (Q, N) matmul
    out: dict[str, list[str]] = {}
    for qi, query in enumerate(queries):
        order = np.argsort(-sim[qi])
        seen: set[str] = set()
        ranked: list[str] = []
        for idx in order:
            p = doc_paths[int(idx)]
            if p not in seen:
                seen.add(p)
                ranked.append(p)
            if len(ranked) >= DEPTH:
                break
        out[query] = ranked
    return out


def _rank(files: list[str], golds: list[str]) -> int | None:
    gn = [_norm(g) for g in golds]
    for i, f in enumerate(files, 1):
        nf = _norm(f)
        if any(nf.endswith(g) or g.endswith(nf) for g in gn):
            return i
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
rescue: list[dict] = []  # lex+zk misses, semantic finds
hurt: list[dict] = []  # semantic misses, lex+zk finds
both_find: list[dict] = []
both_miss: list[dict] = []

true_map_merged: dict[str, list[str]] = {}
for _, _, gtm in golds:
    true_map_merged.update(gtm)

pairs_flat = [
    (q, tid, prefix)
    for _, gpairs, _ in golds
    for q, tid, prefix in gpairs
    if prefix in engines and q in uq.get(prefix, [])
]

done = 0
t_start = time.time()
for prefix, queries in sorted(uq.items()):
    eng = engines.get(prefix)
    if eng is None:
        continue

    # batch-embed all queries for this repo in one matmul
    sem_batch = _semantic_batch(prefix, sorted(queries))

    for query in sorted(queries):
        # find all gold files for this (prefix, query)
        gold_files: list[str] = []
        gold_tids: list[str] = []
        for q, tid, pfx in pairs_flat:
            if pfx == prefix and q == query:
                gold_tids.append(tid)
                gold_files.extend(true_map_merged.get(tid, []))
        if not gold_files:
            continue

        lex_files = _explore(eng, query, zoekt=False)
        zk_files = _explore(eng, query, zoekt=True)
        sem_files = sem_batch.get(query, [])

        r_lex = _rank(lex_files, gold_files)
        r_zk = _rank(zk_files, gold_files)
        r_sem = _rank(sem_files, gold_files)

        # best lexical rank (lex or lex+zk)
        r_best_lex = (
            min(r for r in (r_lex, r_zk) if r is not None) if any(r is not None for r in (r_lex, r_zk)) else None
        )

        entry = {
            "query": query,
            "prefix": prefix,
            "gold_files": gold_files,
            "gold_tids": gold_tids,
            "r_lex": r_lex,
            "r_zk": r_zk,
            "r_sem": r_sem,
            "r_best_lex": r_best_lex,
        }

        lex_hits = r_best_lex is not None and r_best_lex <= DEPTH
        sem_hits = r_sem is not None and r_sem <= DEPTH

        if sem_hits and not lex_hits:
            rescue.append(entry)
        elif lex_hits and not sem_hits:
            hurt.append(entry)
        elif lex_hits and sem_hits:
            both_find.append(entry)
        else:
            both_miss.append(entry)

        done += 1
        if done % 20 == 0 or done == total_queries:
            elapsed = time.time() - t_start
            print(
                f"[mine] {done}/{total_queries} elapsed={elapsed:.0f}s rescue={len(rescue)} hurt={len(hurt)}",
                flush=True,
            )

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
W = 70
print("\n" + "─" * W)
print(f"  embedder : {embedder.name}")
print(f"  queries  : {done}  repos={len(uq)}")
print(f"  RESCUE   : {len(rescue)}  (sem finds, lex+zk misses)")
print(f"  HURT     : {len(hurt)}  (lex+zk finds, sem misses)")
print(f"  BOTH     : {len(both_find)}  (both find)")
print(f"  NEITHER  : {len(both_miss)}  (both miss)")


def _mrr(entries: list[dict], key: str) -> float:
    rr = sum(1.0 / e[key] for e in entries if e.get(key) and e[key] <= DEPTH)
    return rr / max(len(entries), 1)


all_entries = rescue + hurt + both_find + both_miss
print()
print(f"  MRR (lex)     : {_mrr(all_entries, 'r_lex'):.4f}")
print(f"  MRR (lex+zk)  : {_mrr(all_entries, 'r_zk'):.4f}")
print(f"  MRR (semantic): {_mrr(all_entries, 'r_sem'):.4f}")

if rescue:
    print("=== TOP RESCUE QUERIES (semantic wins, lex+zk misses) ===")
    rescue_sorted = sorted(rescue, key=lambda e: e["r_sem"] or 99)
    for e in rescue_sorted[:20]:
        short = e["prefix"].split("__")[-1]
        print(
            f"  [{short}] r_lex={e['r_lex'] or '-':>3}  r_zk={e['r_zk'] or '-':>3}  "
            f"r_sem={e['r_sem']:>2}  {e['query']!r}"
        )

if hurt:
    print("=== HURT QUERIES (lex+zk wins, semantic misses) ===")
    hurt_sorted = sorted(hurt, key=lambda e: e["r_best_lex"] or 99)
    for e in hurt_sorted[:10]:
        short = e["prefix"].split("__")[-1]
        print(
            f"  [{short}] r_lex={e['r_lex'] or '-':>3}  r_zk={e['r_zk'] or '-':>3}  "
            f"r_sem={e['r_sem'] or '-':>3}  {e['query']!r}"
        )

print("─" * W)

# ---------------------------------------------------------------------------
# Write gold JSON (rescued pairs only)
# ---------------------------------------------------------------------------
if rescue:
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # build the same format as bench_pairs_def_gold.json
    out_pairs: list[list] = []
    out_true_map: dict[str, list[str]] = {}
    seen_pairs: set[tuple[str, str]] = set()

    for e in rescue:
        for tid in e["gold_tids"]:
            key = (e["query"], tid)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            out_pairs.append([e["query"], tid, e["prefix"]])
            out_true_map[tid] = [_norm(f) for f in true_map_merged.get(tid, [])]

    out_doc = {
        "gold_kind": "semantic_rescue",
        "description": (
            f"Queries where lexical+zoekt misses but {embedder.name} semantic search rescues. "
            f"Mined by experiments/retrieval_symbol_vote/semantic_strength.py."
        ),
        "embedder": embedder.name,
        "n_rescue": len(rescue),
        "n_hurt": len(hurt),
        "repos": repos,
        "pairs": out_pairs,
        "true_map": out_true_map,
    }
    with open(out_path, "w") as f:
        json.dump(out_doc, f, indent=2)
    print(f"\n[mine] wrote {len(out_pairs)} rescue pairs -> {out_path}")
else:
    print("\n[mine] no rescue pairs found; output file not written.")
