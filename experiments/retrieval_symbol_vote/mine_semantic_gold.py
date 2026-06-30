"""Mine semantic-only golden queries from doc_summaries and symbol descriptions.

Strategy: for each symbol in the index DB that has a doc_summary, use the
doc_summary text (natural language) as a query.  Test it against:
  - lex+zoekt arm (tool_explore)
  - semantic arm  (cosine over symbol embeddings)

Keep only pairs where:
  - semantic finds the gold file in top-K (default 5)
  - lex+zoekt misses it (rank > K or None)

This produces a gold set specifically designed to measure semantic lift, unlike
the SWE-bench-style pairs which favour exact token matching.

Optionally (--paraphrase) call Claude to rephrase symbol names into conceptual
descriptions before testing.  Requires ANTHROPIC_API_KEY.

Usage:
    # mine from doc_summaries (no LLM needed)
    ATELIER_CODE_EMBEDDER=nomic \
        uv run python experiments/retrieval_symbol_vote/mine_semantic_gold.py

    # mine + paraphrase symbol names via Claude
    ATELIER_CODE_EMBEDDER=nomic --paraphrase \
        uv run python experiments/retrieval_symbol_vote/mine_semantic_gold.py

    # quick test on one repo
    ATELIER_CODE_EMBEDDER=nomic FITNESS_REPO=seaborn \
        uv run python experiments/retrieval_symbol_vote/mine_semantic_gold.py --per-repo 200

Output: benchmarks/codebench/data/bench_pairs_semantic_gold.json
        (merged with any existing rescue pairs from semantic_strength.py)
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
ap = argparse.ArgumentParser()
ap.add_argument("--per-repo", type=int, default=500, help="Max symbols to sample per repo")
ap.add_argument("--sem-k", type=int, default=5, help="Semantic must rank gold file within top-K")
ap.add_argument("--lex-k", type=int, default=10, help="Lex+zoekt must rank gold file outside top-K (miss)")
ap.add_argument("--min-summary", type=int, default=20, help="Min doc_summary length (chars) to use as query")
ap.add_argument("--max-summary", type=int, default=120, help="Max doc_summary length for query (truncate)")
ap.add_argument(
    "--paraphrase", action="store_true", help="Use Claude to paraphrase symbol names (needs ANTHROPIC_API_KEY)"
)
ap.add_argument("--repo", default=os.environ.get("FITNESS_REPO", ""), help="Filter to repos containing this substring")
ap.add_argument(
    "--gold", default="benchmarks/codebench/data/bench_pairs_def_gold.json", help="Source gold to get repos list from"
)
ap.add_argument(
    "--out",
    default="benchmarks/codebench/data/bench_pairs_semantic_gold.json",
    help="Output path (merged with existing content)",
)
args = ap.parse_args()

EMBEDDER_PIN = os.environ.get("ATELIER_CODE_EMBEDDER", "nomic")
# Scrub from env before engine init (same fix as semantic_strength.py)
for _k in ("ATELIER_CODE_EMBEDDER", "ATELIER_NOMIC_DIM", "ATELIER_BGE_MAX_SEQ"):
    os.environ.pop(_k, None)

# ---------------------------------------------------------------------------
# Load repos
# ---------------------------------------------------------------------------
with open(args.gold) as f:
    _d = json.load(f)
repos: dict = _d["repos"]

if args.repo:
    repos = {p: m for p, m in repos.items() if args.repo in p}

# ---------------------------------------------------------------------------
# Load embedder
# ---------------------------------------------------------------------------
embedder = make_code_embedder(pin=EMBEDDER_PIN)
print(f"[mine-sem] embedder={embedder.name} dim={embedder.dim}", flush=True)


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def _db_for(meta: dict) -> Path | None:
    if meta.get("db"):
        p = Path(meta["db"])
        return p if p.exists() else None
    p = Path("/tmp") / workspace_key(Path(meta["ws"]).resolve()) / "code_context.sqlite"
    return p if p.exists() else None


# ---------------------------------------------------------------------------
# Build engines
# ---------------------------------------------------------------------------
engines: dict[str, CodeContextEngine] = {}
for prefix, meta in repos.items():
    if not Path(meta["ws"]).is_dir():
        continue
    db = _db_for(meta)
    eng = CodeContextEngine(Path(meta["ws"]), db_path=db, autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)  # type: ignore[method-assign]
    eng._cache_set = lambda *a, **k: None  # type: ignore[method-assign]
    eng._schema_ready = True
    if get_zoekt_supervisor is not None:
        with contextlib.suppress(Exception):
            get_zoekt_supervisor(Path(meta["ws"]))
    engines[prefix] = eng

if get_zoekt_supervisor is not None:
    for eng in engines.values():
        with contextlib.suppress(Exception):
            get_zoekt_supervisor(eng.repo_root).server.wait_until_searchable(20.0)


# ---------------------------------------------------------------------------
# Paraphrase helper (optional Claude call)
# ---------------------------------------------------------------------------
def _paraphrase_batch(names: list[str]) -> list[str]:
    """Ask Claude to rephrase symbol names as conceptual natural-language queries."""
    try:
        import anthropic
    except ImportError:
        print("[paraphrase] anthropic not installed; skipping", flush=True)
        return names
    client = anthropic.Anthropic()
    prompt = (
        "You are helping build a code retrieval benchmark. "
        "For each symbol name below, write a SHORT (5-12 word) natural-language "
        "description of what it likely does or represents. "
        "Do NOT include the exact symbol name. "
        "Return one description per line, same order as input.\n\n" + "\n".join(names)
    )
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    lines = msg.content[0].text.strip().splitlines()
    # pad / truncate to same length
    while len(lines) < len(names):
        lines.append(names[len(lines)])
    return [ln.strip() for ln in lines[: len(names)]]


# ---------------------------------------------------------------------------
# Per-repo: embed corpus, generate candidates, test lex arm
# ---------------------------------------------------------------------------
def _explore(eng: CodeContextEngine, query: str, *, zoekt: bool) -> list[str]:
    if zoekt:
        os.environ["ATELIER_ZOEKT_MODE"] = "installed"
        os.environ.pop("ATELIER_ZOEKT_GATE", None)
    else:
        os.environ["ATELIER_ZOEKT_MODE"] = "off"
    try:
        payload = eng.tool_explore(query, max_files=args.lex_k, auto_index=False)
        return [_norm(f.get("path", "")) for f in payload.get("files", [])]
    except Exception:  # noqa: BLE001
        return []


def _lex_misses(eng: CodeContextEngine, query: str, gold_file: str) -> bool:
    """Return True if both lex-only and lex+zoekt miss gold_file in top-K."""
    for zoekt in (False, True):
        files = _explore(eng, query, zoekt=zoekt)
        gn = _norm(gold_file)
        for f in files:
            nf = _norm(f)
            if nf.endswith(gn) or gn.endswith(nf):
                return False
    return True


all_rescue: list[dict] = []

for prefix, meta in repos.items():
    eng = engines.get(prefix)
    if eng is None:
        continue
    db = _db_for(meta)
    if db is None:
        print(f"[skip] {prefix}: no DB", flush=True)
        continue

    con = sqlite3.connect(str(db))
    rows = con.execute(
        "SELECT file_path, symbol_name, kind, doc_summary, qualified_name "
        "FROM symbols WHERE file_path IS NOT NULL "
        "ORDER BY RANDOM() LIMIT ?",
        (args.per_repo * 4,),  # oversample; we'll filter
    ).fetchall()
    con.close()

    # --- corpus vectors for semantic arm ---
    doc_texts = [f"{r[1]} {r[2]} {r[3] or ''}".strip() for r in rows]
    doc_paths = [_norm(r[0]) for r in rows]
    t0 = time.time()
    doc_mat = np.array(embedder.embed_documents(doc_texts), dtype=np.float32)
    print(f"[{prefix.split('__')[-1]}] {len(rows)} symbols embedded in {time.time() - t0:.1f}s", flush=True)

    # --- build query candidates ---
    # Source 1: doc_summary (natural language, high semantic signal)
    candidates: list[tuple[str, str]] = []  # (query_text, gold_file_path)
    for r in rows:
        fp, name, _kind, summary, _qname = r
        if summary and args.min_summary <= len(summary) <= args.max_summary:
            # trim trailing punctuation noise
            q = summary.rstrip(". \t\n")
            candidates.append((q, _norm(fp)))

    # Source 2: paraphrased symbol names (optional)
    if args.paraphrase:
        sym_rows = [r for r in rows if r[1] and len(r[1]) > 4][: args.per_repo]
        names = [r[1] for r in sym_rows]
        print(f"  paraphrasing {len(names)} names via Claude...", flush=True)
        paraphrases = _paraphrase_batch(names)
        for (fp, name, _k, _s, _qn), para in zip(sym_rows, paraphrases, strict=False):
            if len(para) > 8 and name.lower() not in para.lower():
                candidates.append((para, _norm(fp)))

    # deduplicate by query
    seen_q: set[str] = set()
    unique_candidates: list[tuple[str, str]] = []
    for q, fp in candidates:
        if q not in seen_q:
            seen_q.add(q)
            unique_candidates.append((q, fp))

    unique_candidates = unique_candidates[: args.per_repo]
    print(f"  {len(unique_candidates)} candidate queries", flush=True)

    if not unique_candidates:
        continue

    # --- semantic ranking (batch matmul) ---
    query_texts = [q for q, _ in unique_candidates]
    gold_files = [fp for _, fp in unique_candidates]

    t0 = time.time()
    q_mat = np.array(embedder.embed_queries(query_texts), dtype=np.float32)
    sim = q_mat @ doc_mat.T  # (Q, N)
    print(f"  query embed + sim in {time.time() - t0:.2f}s", flush=True)

    # keep only queries where semantic rank <= sem_k
    sem_hits: list[tuple[int, str, str]] = []  # (sem_rank, query, gold_file)
    for qi, (query, gold_file) in enumerate(unique_candidates):
        order = np.argsort(-sim[qi])
        seen_files: set[str] = set()
        rank = None
        for ri, idx in enumerate(order, 1):
            p = doc_paths[int(idx)]
            if p not in seen_files:
                seen_files.add(p)
                if p.endswith(gold_file) or gold_file.endswith(p):
                    rank = ri
                    break
            if ri > args.sem_k * 3:  # early exit
                break
        if rank is not None and rank <= args.sem_k:
            sem_hits.append((rank, query, gold_file))

    print(f"  {len(sem_hits)} semantic hits (rank<={args.sem_k}); testing lex arm...", flush=True)

    # --- lex arm: only test semantic hits ---
    repo_rescue: list[dict] = []
    for sem_rank, query, gold_file in sem_hits:
        if _lex_misses(eng, query, gold_file):
            repo_rescue.append(
                {
                    "query": query,
                    "prefix": prefix,
                    "gold_file": gold_file,
                    "sem_rank": sem_rank,
                    "source": "doc_summary" if not args.paraphrase else "doc_summary+paraphrase",
                }
            )
            print(f"  ✓ RESCUE r={sem_rank}: {query!r} -> {gold_file}", flush=True)

    print(f"  rescued {len(repo_rescue)}/{len(sem_hits)} queries for {prefix}", flush=True)
    all_rescue.extend(repo_rescue)

# ---------------------------------------------------------------------------
# Merge with existing gold file and write
# ---------------------------------------------------------------------------
out_path = Path(args.out)
existing_pairs: list = []
existing_true_map: dict = {}
existing_desc = ""
if out_path.exists():
    existing = json.load(open(out_path))
    existing_pairs = existing.get("pairs", [])
    existing_true_map = existing.get("true_map", {})
    existing_desc = existing.get("description", "")
    print(f"[merge] existing: {len(existing_pairs)} pairs")

# deduplicate by (query, prefix)
existing_keys = {(p[0], p[2]) for p in existing_pairs}
new_pairs: list = list(existing_pairs)
new_true_map: dict = dict(existing_true_map)

added = 0
for e in all_rescue:
    key = (e["query"], e["prefix"])
    if key in existing_keys:
        continue
    existing_keys.add(key)
    tid = f"sem_{len(new_pairs):04d}"
    new_pairs.append([e["query"], tid, e["prefix"]])
    new_true_map[tid] = [e["gold_file"]]
    added += 1

out_doc = {
    "gold_kind": "semantic_rescue",
    "description": (
        f"Queries where lex+zoekt misses but semantic search rescues. "
        f"Sources: semantic_strength.py (benchmark pairs) + mine_semantic_gold.py (doc_summary). "
        f"Embedder: {embedder.name}."
    ),
    "embedder": embedder.name,
    "n_total": len(new_pairs),
    "n_added_this_run": added,
    "repos": repos,
    "pairs": new_pairs,
    "true_map": new_true_map,
}
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w") as f:
    json.dump(out_doc, f, indent=2)

W = 64
print("\n" + "─" * W)
print(f"  embedder : {embedder.name}")
print(f"  rescued  : {len(all_rescue)} new pairs this run")
print(f"  merged   : {added} added  (skipped {len(all_rescue) - added} duplicates)")
print(f"  total    : {len(new_pairs)} pairs in {out_path}")
print("─" * W)

if all_rescue:
    print("\nTop rescued queries:")
    for e in sorted(all_rescue, key=lambda x: x["sem_rank"])[:20]:
        short = e["prefix"].split("__")[-1]
        print(f"  [{short}] r={e['sem_rank']} {e['query']!r}")
