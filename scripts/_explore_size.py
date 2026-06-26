"""Scratch: measure explore payload size (raw dict vs rendered markdown) and noise,
so the bloat fixes are grounded in real before/after token counts."""

import os

os.environ["ATELIER_CODE_EMBEDDER"] = "local"  # no GPU; measuring payload size/noise, not semantic quality
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.core.capabilities.code_context.renderer import _render_explore

data = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
ws = data["repos"]["django__django"]["ws"]
eng = CodeContextEngine(Path(ws), db_path=Path("/tmp/fused_django__django.db"), autosync_enabled=False)
eng._cache_get = lambda *a, **k: (False, None)  # bypass persisted retrieval cache (stale pre-edit results)
eng._cache_set = lambda *a, **k: None

CASES = [
    ("timezone session token cache validate", 8),  # bag-of-terms (broad)
    ("timezone session token cache validate", 1),  # explicit tiny cap -- must be respected
    ("how are timezones converted for sqlite", 8),  # concept query
    ("get_current_timezone_name", 8),  # exact symbol -> anchor gate
]


def toks(s: str) -> int:
    return len(s) // 4


for q, mf in CASES:
    p = eng.tool_explore(q, max_files=mf, auto_index=False)
    raw = json.dumps(p)
    md = _render_explore(p) or ""
    ep = p.get("entry_points", [])
    files = p.get("files", [])
    arf = p.get("additional_relevant_files", [])
    rel = p.get("relationships")
    rel_empty = (not rel) or not any((rel or {}).values())
    arf_dups = len(arf) - len(set(arf))
    print(f"\nQ: {q[:45]!r}  max_files={mf}")
    print(f"  raw_dict={toks(raw):5d} tok   rendered_md={toks(md):5d} tok   ({toks(raw) - toks(md)} saved by render)")
    print(
        f"  entry_points={len(ep)}  files={len(files)}  additional_relevant_files={len(arf)} (dups={arf_dups})  relationships_present={'relationships' in p} empty={rel_empty}"
    )
    if ep:
        scores = [round(e.get("score") or 0, 4) for e in ep]
        print(f"  scores: max={max(scores)} min={min(scores)}  -> {scores[:12]}")

from atelier.core.capabilities.code_context.engine import _exact_symbol_hits  # noqa: E402

q = "get_current_timezone_name"
rs = eng.search_symbols(q, limit=20, snippet="none", auto_index=False)
eh = _exact_symbol_hits(rs, q)
print(
    f"\nDEBUG exact: search_symbols->{len(rs)}  exact_hits->{len(eh)}  top5_names={[s.symbol_name for s in rs[:5]]}  top5_scores={[round(s.score or 0, 1) for s in rs[:5]]}"
)
