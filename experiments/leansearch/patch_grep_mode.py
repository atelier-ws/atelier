"""grep `mode`: terse canonical names (content/map/paths/counts) are ambiguous, so
the model reaches for self-documenting names (file_paths_with_content). Drop the
strict Literal (what rejects them) + add a forgiving normalizer: descriptive names
and common variants map to canonical; unknown -> content. Never 422 on mode.
"""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
t = open(MCP, encoding="utf-8").read()

# A) add normalizer right after _GREP_MODE_ALIASES
anchor_a = (
    "_GREP_MODE_ALIASES: dict[str, str] = {\n"
    '    "content": "file_paths_with_content",\n'
    '    "map": "ranked_file_map",\n'
    '    "paths": "file_paths_only",\n'
    '    "counts": "file_paths_with_match_count",\n'
    "}\n"
)
norm = (
    "\n\n# Forgiving mode normalisation: the model prefers self-documenting names\n"
    "# (file_paths_with_content) over the terse canonical ones, so accept both forms\n"
    "# plus common variants and default unknowns to 'content' -- grep never 422s on mode.\n"
    "_GREP_MODE_CANON: dict[str, str] = {\n"
    '    "content": "content", "map": "map", "paths": "paths", "counts": "counts",\n'
    '    "file_paths_with_content": "content", "files_with_content": "content", "file_content": "content",\n'
    '    "ranked_file_map": "map", "file_map": "map", "ranked": "map",\n'
    '    "file_paths_only": "paths", "file_paths": "paths", "files": "paths", "filenames": "paths",\n'
    '    "file_paths_with_match_count": "counts", "match_count": "counts", "count": "counts",\n'
    "}\n\n\n"
    "def _normalize_grep_mode(mode: object) -> str:\n"
    '    """Map any reasonable mode spelling to a canonical short name; unknown -> content."""\n'
    '    return _GREP_MODE_CANON.get(str(mode or "content").strip().lower(), "content")\n'
)
if "_normalize_grep_mode" in t:
    print("normalizer already present")
elif anchor_a in t:
    t = t.replace(anchor_a, anchor_a + norm, 1)
    print("A: normalizer added")
else:
    print("ANCHOR A NOT FOUND")
    raise SystemExit

# B) mode param: Literal -> str (so descriptive aliases are not rejected)
anchor_b = (
    "    mode: Annotated[\n"
    '        Literal["content", "map", "paths", "counts"],\n'
    "        Field(\n"
    "            description=(\n"
    '                "content: matched lines+context (default); map: ranked file pointers; "\n'
    '                "paths: matching file paths; counts: path + match count."\n'
    "            )\n"
    "        ),\n"
    '    ] = "content",\n'
)
new_b = (
    "    mode: Annotated[\n"
    "        str,\n"
    "        Field(\n"
    "            description=(\n"
    '                "content: matched lines+context (default); map: ranked file pointers; "\n'
    '                "paths: matching file paths; counts: path + match count. "\n'
    '                "Descriptive aliases (e.g. file_paths_with_content) are accepted."\n'
    "            )\n"
    "        ),\n"
    '    ] = "content",\n'
)
if anchor_b in t:
    t = t.replace(anchor_b, new_b, 1)
    print("B: mode Literal -> str")
elif '        str,\n        Field(\n            description=(\n                "content: matched' in t:
    print("B: already str")
else:
    print("ANCHOR B NOT FOUND")
    raise SystemExit

# C) normalize at the consumption point
anchor_c = "        _GREP_MODE_ALIASES.get(mode, mode),\n"
new_c = '        _GREP_MODE_ALIASES.get(_normalize_grep_mode(mode), "file_paths_with_content"),\n'
if anchor_c in t:
    t = t.replace(anchor_c, new_c, 1)
    print("C: native_mode normalized")
elif "_normalize_grep_mode(mode)" in t:
    print("C: already normalized")
else:
    print("ANCHOR C NOT FOUND")
    raise SystemExit

open(MCP, "w", encoding="utf-8").write(t)
print("done")
