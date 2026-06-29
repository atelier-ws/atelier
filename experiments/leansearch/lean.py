"""Lean (re-tuned) projection for code_search + offline harness over the corpus.

Design v2 -- less aggressive, budget-based:
  * code_search should hand back enough context to go straight to one BULK edit
    (the agent supports bulk read/edit), not force a sequential read loop.
  * rank files by best entry-point score (path-level), seed-boosted; greedily
    include whole files' source up to SOURCE_BUDGET chars (always >=1 file).
  * keep candidate signatures (above score floor) + surfaced file paths so the
    agent can bulk-read the rest in ONE call if needed (e.g. test files).
  * strip non-actionable metadata (experiment/id/provenance/...). Generic.

Run:  uv run --project benchmarks python experiments/leansearch/lean.py [BUDGET]
"""
from __future__ import annotations

import json
import sys

ROOT = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch"

SOURCE_BUDGET = 9000   # max chars of source returned (greedy, whole-file)
REL_FLOOR = 0.10       # candidate signatures must score >= 10% of top
MAX_CANDIDATES = 10   # max related-symbol signatures (the cross-file nav map)


def _score_of(sym):
    try:
        return float(sym.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _sig(sym):
    qn = sym.get("qualified_name") or sym.get("name") or "?"
    return f"{qn} @ {sym.get('path', '?')}:{sym.get('line', '?')}"


def _clean_section(sec):
    return {
        "path": sec.get("path"),
        "qualified_name": sec.get("qualified_name") or sec.get("name"),
        "line": sec.get("line"),
        "end_line": sec.get("end_line"),
        "content": sec.get("content", ""),
    }


def project(result, max_files=8, seed_files=None, budget=SOURCE_BUDGET):
    if not isinstance(result, dict):
        return result
    eps = sorted((result.get("entry_points") or []), key=_score_of, reverse=True)
    files = result.get("files") or []
    exact = bool(result.get("exact_match"))
    top = _score_of(eps[0]) if eps else 0.0
    floor = top * REL_FLOOR

    epscore_by_path = {}
    for e in eps:
        p = e.get("path")
        if p is not None:
            epscore_by_path[p] = max(epscore_by_path.get(p, 0.0), _score_of(e))

    seed_norm = {s.rstrip("/") for s in (seed_files or [])}

    def is_seed(path):
        return bool(path) and any(path == s or path.startswith(s + "/") for s in seed_norm)

    def rank_key(f):
        return (1 if is_seed(f.get("path")) else 0, epscore_by_path.get(f.get("path"), 0.0))

    ranked = sorted(files, key=rank_key, reverse=True)

    # greedily include whole files' source up to budget (always >= first file)
    out_files, seen_paths, used = [], set(), 0
    for f in ranked:
        secs = [_clean_section(s) for s in (f.get("source_sections") or [])]
        if not secs:
            continue
        size = sum(len(s["content"]) for s in secs)
        if out_files and used + size > budget:
            break
        out_files.append({"path": f.get("path"), "sections": secs})
        seen_paths.add(f.get("path"))
        used += size
        if used >= budget:
            break

    # Cross-file symbol MAP: top-K entry points as compact signatures, NOT
    # score-floor-gated. On multi-file tasks (e.g. several classes each defining
    # the queried method) the secondary symbols score far below the top hit; the
    # old floor cut them, so the agent re-searched the same term repeatedly to
    # rediscover each definition. Keeping the map (cheap: ~50 chars each) lets it
    # navigate every related site in one call.
    related = []
    seen_sig = set()
    for e in eps:
        sig = _sig(e)
        if sig in seen_sig:
            continue
        seen_sig.add(sig)
        related.append(sig)
        if len(related) >= MAX_CANDIDATES:
            break

    # File-level fallback: surfaced paths we didn't return source for. Cheap, and
    # the only signal on vague queries that match no precise symbol (the engine
    # returns bare file paths). Keep it alongside the symbol map.
    cand_files = []
    for f in ranked:
        p = f.get("path")
        if p and p not in seen_paths and p not in cand_files:
            cand_files.append(p)
    for p in (result.get("additional_relevant_files") or []):
        if p and p not in seen_paths and p not in cand_files:
            cand_files.append(p)

    lean = {"exact_match": exact, "files": out_files}
    if related:
        lean["related_symbols"] = related
    if cand_files:
        lean["candidate_files"] = cand_files[:MAX_CANDIDATES]
    if result.get("truncated"):
        lean["truncated"] = True
    return lean


def _ser(o):
    return json.dumps(o, separators=(",", ":"))


def _gold_hit(text, gold_files):
    return any(g in text for g in (gold_files or []) if g != "uv.lock")


def main():
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else SOURCE_BUDGET
    gold = json.load(open(f"{ROOT}/gold.json"))
    rows = [json.loads(line) for line in open(f"{ROOT}/corpus.jsonl") if line.strip()]
    cs = [r for r in rows if r["tool"] == "code_search" and r["result"] is not None]
    print(f"budget={budget}  code_search calls: {len(cs)}\n")
    hdr = f"{'task':26} {'orig':>7} {'lean':>6} {'cut%':>5} {'srcF':>4} {'goldL':>5}  query"
    print(hdr)
    print("-" * len(hdr))
    to = tl = gok = ngold = 0
    for r in cs:
        orig = r["result_chars"]
        inp = r["input"] if isinstance(r["input"], dict) else {}
        raw = inp.get("paths") or inp.get("path")
        seeds = ([p.strip() for p in raw.split(",")] if isinstance(raw, str)
                 else raw if isinstance(raw, list) else None)
        lean = project(r["result"], max_files=inp.get("max_files", 8), seed_files=seeds, budget=budget)
        leant = _ser(lean)
        gf = gold.get(r["task"], [])
        if _gold_hit(_ser(r["result"]), gf):
            ngold += 1
            if _gold_hit(leant, gf):
                gok += 1
        to += orig
        tl += len(leant)
        q = (inp.get("query", ""))[:36]
        print(f"{r['task']:26} {orig:7} {len(leant):6} {100 * (1 - len(leant) / orig):4.0f}% {len(lean['files']):4} {_gold_hit(leant, gf)!s:>5}  {q}")
    print("-" * len(hdr))
    print(f"TOTAL  orig={to:,}  lean={tl:,}  reduction={100 * (1 - tl / to):.0f}%   gold retained {gok}/{ngold}")


if __name__ == "__main__":
    main()
