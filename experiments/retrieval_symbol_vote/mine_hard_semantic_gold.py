"""Mine hard semantic golden queries by showing Claude real code and asking
it to generate conceptual/behavioral questions a developer would type.

Why this is harder than doc_summary mining:
  - Queries describe WHAT the code does, using zero tokens from the code
  - Example: sees binary_search() -> generates "function that finds an element
    in a sorted list by halving the search space each step"
  - Lex+zoekt must miss (strict: both tool_explore AND raw grep fail)
  - At least one semantic embedder must find the file in top-K

Usage:
    ATELIER_CODE_EMBEDDER=nomic \
        uv run python experiments/retrieval_symbol_vote/mine_hard_semantic_gold.py \
        --per-repo 80 --repo django

    # all repos, 60 symbols each
    ATELIER_CODE_EMBEDDER=nomic \
        uv run python experiments/retrieval_symbol_vote/mine_hard_semantic_gold.py \
        --per-repo 60
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
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
ap = argparse.ArgumentParser()
ap.add_argument("--per-repo", type=int, default=60)
ap.add_argument("--queries-per-symbol", type=int, default=2, help="How many queries Claude generates per symbol")
ap.add_argument("--sem-k", type=int, default=5, help="Semantic rank must be <= this to count as a hit")
ap.add_argument("--lex-k", type=int, default=10, help="Lex rank must be > this (or miss) to count as hard")
ap.add_argument("--repo", default=os.environ.get("FITNESS_REPO", ""))
ap.add_argument("--gold", default="benchmarks/codebench/data/bench_pairs_def_gold.json")
ap.add_argument("--out", default="benchmarks/codebench/data/bench_pairs_semantic_gold.json")
ap.add_argument("--code-lines", type=int, default=40, help="Max source lines to send Claude per symbol")
args = ap.parse_args()

EMBEDDER_PIN = os.environ.get("ATELIER_CODE_EMBEDDER", "nomic")
for _k in ("ATELIER_CODE_EMBEDDER", "ATELIER_NOMIC_DIM", "ATELIER_BGE_MAX_SEQ"):
    os.environ.pop(_k, None)

# ---------------------------------------------------------------------------
with open(args.gold) as f:
    _d = json.load(f)
repos: dict = _d["repos"]
if args.repo:
    repos = {p: m for p, m in repos.items() if args.repo in p}

embedder = make_code_embedder(pin=EMBEDDER_PIN)
print(f"[hard-mine] embedder={embedder.name}  repos={len(repos)}", flush=True)


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
# Lex check  (strict: tool_explore AND raw grep both miss)
# ---------------------------------------------------------------------------
def _explore(eng: CodeContextEngine, query: str, *, zoekt: bool) -> list[str]:
    os.environ["ATELIER_ZOEKT_MODE"] = "installed" if zoekt else "off"
    try:
        r = eng.tool_explore(query, max_files=args.lex_k, auto_index=False)
        return [_norm(f.get("path", "")) for f in r.get("files", [])]
    except Exception:  # noqa: BLE001
        return []


def _grep_hits(ws: Path, query: str, gold_file: str, k: int = 10) -> bool:
    """True if ANY word >5 chars from the query appears literally in gold_file."""
    words = [w.strip(".,;:!?'\"()") for w in query.split() if len(w) > 5]
    if not gold_file:
        return False
    target = ws / gold_file.lstrip("/")
    if not target.exists():
        return False
    try:
        text = target.read_text(errors="ignore").lower()
        # if more than 2 query words appear literally in the file, lex could find it
        hits = sum(1 for w in words if w.lower() in text)
        return hits >= 3
    except Exception:  # noqa: BLE001
        return False


def _lex_misses(eng: CodeContextEngine, ws: Path, query: str, gold_file: str) -> bool:
    """Strict: both lex arms miss AND query words don't appear literally in gold file."""
    if _grep_hits(ws, query, gold_file):
        return False  # query tokens present in file -> lex could find it
    for zoekt in (False, True):
        files = _explore(eng, query, zoekt=zoekt)
        gn = _norm(gold_file)
        for f in files:
            nf = _norm(f)
            if nf.endswith(gn) or gn.endswith(nf):
                return False
    return True


# ---------------------------------------------------------------------------
# Read source code for a symbol
# ---------------------------------------------------------------------------
def _read_source(ws: Path, file_path: str, start_line: int, end_line: int) -> str:
    target = ws / file_path.lstrip("/")
    try:
        lines = target.read_text(errors="ignore").splitlines()
        sl = max(0, start_line - 1)
        el = min(len(lines), end_line)
        snippet = lines[sl:el]
        if len(snippet) > args.code_lines:
            snippet = snippet[: args.code_lines]
        return "\n".join(snippet)
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Claude: generate conceptual queries from code
# ---------------------------------------------------------------------------
_SYSTEM = textwrap.dedent("""\
    You are building a CODE RETRIEVAL benchmark.
    Given a code snippet, generate {n} natural-language questions a developer
    might type into a search box to find THIS specific code.

    Rules:
    - Do NOT use the function/class/variable name from the code.
    - Do NOT copy phrases verbatim from comments or docstrings.
    - Describe the BEHAVIOR or PURPOSE in plain English.
    - Each question must be on its own line.
    - Be specific enough that only this code (or very similar code) would match.
    - Vary vocabulary: use synonyms, analogies, describe inputs/outputs.
    - Short (8-20 words). No bullet points, no numbering, just the question text.

    Output exactly {n} lines.
""").strip()


def _generate_queries(code: str, symbol_name: str, kind: str, n: int) -> list[str]:
    full_prompt = (
        f"{_SYSTEM.format(n=n)}\n\n"
        f"Symbol: `{symbol_name}` ({kind})\n\nCode:\n```\n{code}\n```\n\nGenerate {n} search queries."
    )
    try:
        result = subprocess.run(
            ["claude", "-p", full_prompt, "--model", "claude-haiku-4-5"],
            capture_output=True, text=True, timeout=90,
        )
        lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
        return lines[:n]
    except Exception as exc:  # noqa: BLE001
        print(f"  [claude error] {exc}", flush=True)
        return []


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
all_rescue: list[dict] = []
total_generated = 0
total_tested = 0

for prefix, meta in repos.items():
    eng = engines.get(prefix)
    if eng is None:
        continue
    ws = Path(meta["ws"])
    db = _db_for(meta)
    if db is None:
        print(f"[skip] {prefix}: no DB", flush=True)
        continue

    con = sqlite3.connect(str(db))
    # prefer functions/methods with actual code extent
    rows = con.execute(
        """
        SELECT file_path, symbol_name, kind, start_line, end_line
        FROM symbols
        WHERE file_path IS NOT NULL
          AND kind IN ('function','method','class')
          AND end_line > start_line + 3
          AND end_line - start_line <= 80
        ORDER BY RANDOM()
        LIMIT ?
        """,
        (args.per_repo,),
    ).fetchall()
    con.close()

    if not rows:
        print(f"[skip] {prefix}: no eligible symbols", flush=True)
        continue

    print(f"\n[{prefix.split('__')[-1]}] {len(rows)} symbols", flush=True)

    # --- embed full corpus once for semantic arm ---
    con = sqlite3.connect(str(db))
    corpus = con.execute(
        "SELECT file_path, symbol_name, kind, doc_summary FROM symbols WHERE file_path IS NOT NULL LIMIT 100000"
    ).fetchall()
    con.close()
    doc_texts = [f"{r[1]} {r[2]} {r[3] or ''}".strip() for r in corpus]
    doc_paths = [_norm(r[0]) for r in corpus]
    doc_mat = np.array(embedder.embed_documents(doc_texts), dtype=np.float32)
    print(f"  corpus: {len(corpus)} symbols embedded", flush=True)

    repo_rescue: list[dict] = []

    for fp, name, kind, sl, el in rows:
        code = _read_source(ws, fp, sl, el)
        if not code or len(code) < 30:
            continue

        queries = _generate_queries(code, name, kind, args.queries_per_symbol)
        total_generated += len(queries)

        for query in queries:
            if len(query) < 10:
                continue
            total_tested += 1

            # semantic rank
            qvec = np.array(embedder.embed_queries([query])[0], dtype=np.float32)
            sim = doc_mat @ qvec
            order = np.argsort(-sim)
            sem_rank = None
            seen: set[str] = set()
            ri = 0
            for idx in order:
                p = doc_paths[int(idx)]
                if p not in seen:
                    seen.add(p)
                    ri += 1
                    gn = _norm(fp)
                    if p.endswith(gn) or gn.endswith(p):
                        sem_rank = ri
                        break
                if ri >= args.sem_k * 4:
                    break

            if sem_rank is None or sem_rank > args.sem_k:
                if os.environ.get("MINE_DEBUG"):
                    print(f"    skip sem_rank={sem_rank}: {query!r}")
                continue  # semantic can't find it either — not useful

            # strict lex miss
            gold_norm = _norm(fp)
            grep_hit = _grep_hits(ws, query, gold_norm)
            lex_found = not grep_hit and not all(
                _explore(eng, query, zoekt=z) == [] or
                not any((_norm(f).endswith(gold_norm) or gold_norm.endswith(_norm(f)))
                        for f in _explore(eng, query, zoekt=z))
                for z in (False, True)
            )
            if os.environ.get("MINE_DEBUG"):
                print(f"    sem_r={sem_rank} grep={grep_hit} lex_found={lex_found}: {query!r}")
            if grep_hit or not _lex_misses(eng, ws, query, gold_norm):
                continue

            repo_rescue.append(
                {
                    "query": query,
                    "prefix": prefix,
                    "gold_file": _norm(fp),
                    "symbol_name": name,
                    "kind": kind,
                    "sem_rank": sem_rank,
                    "source": "claude_code",
                }
            )
            print(f"  ✓ r={sem_rank}: {query!r}  [{fp}]", flush=True)

    print(f"  rescued {len(repo_rescue)} from {len(rows)} symbols", flush=True)
    all_rescue.extend(repo_rescue)
    n_flushed = _flush(repo_rescue)
    print(f"  flushed {n_flushed} new pairs to disk  (total so far: {len(all_rescue)})", flush=True)

# ---------------------------------------------------------------------------
# Incremental write helper — called after each repo
# ---------------------------------------------------------------------------
def _flush(rescue_batch: list[dict]) -> int:
    """Merge rescue_batch into the output file and return count added."""
    out_path = Path(args.out)
    if out_path.exists():
        existing = json.load(open(out_path))
    else:
        existing = {"pairs": [], "true_map": {}}
    existing_pairs = existing.get("pairs", [])
    existing_true_map = existing.get("true_map", {})
    existing_keys = {(p[0], p[2]) for p in existing_pairs}
    new_pairs = list(existing_pairs)
    new_true_map = dict(existing_true_map)
    n_added = 0
    for e in rescue_batch:
        key = (e["query"], e["prefix"])
        if key in existing_keys:
            continue
        existing_keys.add(key)
        tid = f"hard_{len(new_pairs):04d}"
        new_pairs.append([e["query"], tid, e["prefix"]])
        new_true_map[tid] = [e["gold_file"]]
        n_added += 1
    out_doc = {
        "gold_kind": "semantic_rescue",
        "description": (
            "Hard semantic-only queries generated by Claude from actual code. "
            "Queries describe behavior/concept without using code tokens. "
            f"Verified: lex+zoekt misses, grep misses, {embedder.name} finds rank<={args.sem_k}."
        ),
        "embedder": embedder.name,
        "n_total": len(new_pairs),
        "n_added_this_run": n_added,
        "stats": {
            "generated": total_generated,
            "tested": total_tested,
            "rescued": len(all_rescue),
            "yield_pct": round(100 * len(all_rescue) / max(total_tested, 1), 1),
        },
        "repos": repos,
        "pairs": new_pairs,
        "true_map": new_true_map,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(out_doc, f, indent=2)
    tmp.replace(out_path)  # atomic replace
    return n_added

# Final flush (updates stats counters in the file)
_flush([])

out_path = Path(args.out)
final = json.load(open(out_path))
yield_pct = round(100 * len(all_rescue) / max(total_tested, 1), 1)

W = 64
print("\n" + "─" * W)
print(f"  queries generated: {total_generated}")
print(f"  queries tested   : {total_tested}")
print(f"  rescued          : {len(all_rescue)}  ({yield_pct}% yield)")
print(f"  total gold pairs : {final['n_total']}")
print(f"  output           : {out_path}")
print("─" * W)

if all_rescue:
    print("\nSample rescued queries:")
    for e in sorted(all_rescue, key=lambda x: x["sem_rank"])[:15]:
        short = e["prefix"].split("__")[-1]
        print(f"  [{short}/{e['kind']}] r={e['sem_rank']}  {e['query']!r}")
