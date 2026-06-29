"""Patch the worktree's _lean_code_search_view: floor-gated other_candidates ->
no-floor related_symbols map (the cross-file nav the matplotlib runaway needed).
Idempotent.
"""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"

OLD = """    candidates: list[str] = []
    for e in eps:
        if e.get("path") in seen_paths:
            continue
        if _lean_score(e) < floor:
            break
        candidates.append(_lean_sig(e))
        if len(candidates) >= _LEAN_MAX_CANDIDATES:
            break"""

NEW = """    # Cross-file symbol map: top-K entry points as compact signatures, NOT
    # score-floor-gated. On multi-file tasks the secondary symbols (the same
    # method on sibling classes) score far below the top hit; gating them made
    # the agent re-search the term to rediscover each site. Keeping the map lets
    # it navigate every related site in one call.
    candidates: list[str] = []
    seen_sig: set[str] = set()
    for e in eps:
        sig = _lean_sig(e)
        if sig in seen_sig:
            continue
        seen_sig.add(sig)
        candidates.append(sig)
        if len(candidates) >= _LEAN_MAX_CANDIDATES:
            break"""

text = open(MCP, encoding="utf-8").read()
if NEW.split(chr(10))[6] in text:
    print("already patched")
elif OLD in text:
    text = text.replace(OLD, NEW).replace(
        'lean["other_candidates"] = candidates', 'lean["related_symbols"] = candidates'
    )
    open(MCP, "w", encoding="utf-8").write(text)
    print("patched view: related_symbols (no floor) + key rename")
else:
    print("ANCHOR NOT FOUND")
