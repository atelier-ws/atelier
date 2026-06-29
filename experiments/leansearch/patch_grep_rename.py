"""Rename grep mode canonical names to self-documenting forms so the model uses
them confidently instead of defaulting to the verbose file_paths_with_content:
  content -> with_content, map -> ranked_map, paths -> paths_only, counts -> count_only.
The normalizer still absorbs old terse names, verbose names, and variants.
"""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
t = open(MCP, encoding="utf-8").read()
edits = []

# 1) _GREP_MODE_ALIASES keys -> new canonical
edits.append(
    (
        "_GREP_MODE_ALIASES: dict[str, str] = {\n"
        '    "content": "file_paths_with_content",\n'
        '    "map": "ranked_file_map",\n'
        '    "paths": "file_paths_only",\n'
        '    "counts": "file_paths_with_match_count",\n'
        "}\n",
        "_GREP_MODE_ALIASES: dict[str, str] = {\n"
        '    "with_content": "file_paths_with_content",\n'
        '    "ranked_map": "ranked_file_map",\n'
        '    "paths_only": "file_paths_only",\n'
        '    "count_only": "file_paths_with_match_count",\n'
        "}\n",
    )
)

# 2) _GREP_MODE_CANON -> map everything (new, old terse, verbose, variants) to new canonical
edits.append(
    (
        "_GREP_MODE_CANON: dict[str, str] = {\n"
        '    "content": "content", "map": "map", "paths": "paths", "counts": "counts",\n'
        '    "file_paths_with_content": "content", "files_with_content": "content", "file_content": "content",\n'
        '    "ranked_file_map": "map", "file_map": "map", "ranked": "map",\n'
        '    "file_paths_only": "paths", "file_paths": "paths", "files": "paths", "filenames": "paths",\n'
        '    "file_paths_with_match_count": "counts", "match_count": "counts", "count": "counts",\n'
        "}\n",
        "_GREP_MODE_CANON: dict[str, str] = {\n"
        '    "with_content": "with_content", "ranked_map": "ranked_map", "paths_only": "paths_only", "count_only": "count_only",\n'
        '    "content": "with_content", "map": "ranked_map", "paths": "paths_only", "counts": "count_only",\n'
        '    "file_paths_with_content": "with_content", "files_with_content": "with_content", "file_content": "with_content",\n'
        '    "ranked_file_map": "ranked_map", "file_map": "ranked_map", "ranked": "ranked_map",\n'
        '    "file_paths_only": "paths_only", "file_paths": "paths_only", "files": "paths_only", "filenames": "paths_only",\n'
        '    "file_paths_with_match_count": "count_only", "match_count": "count_only", "count": "count_only",\n'
        "}\n",
    )
)

# 3) normalizer default -> with_content
edits.append(
    (
        '    return _GREP_MODE_CANON.get(str(mode or "content").strip().lower(), "content")\n',
        '    return _GREP_MODE_CANON.get(str(mode or "with_content").strip().lower(), "with_content")\n',
    )
)

# 4) mode param description + default
edits.append(
    (
        "    mode: Annotated[\n        str,\n        Field(\n            description=(\n"
        '                "content: matched lines+context (default); map: ranked file pointers; "\n'
        '                "paths: matching file paths; counts: path + match count. "\n'
        '                "Descriptive aliases (e.g. file_paths_with_content) are accepted."\n'
        '            )\n        ),\n    ] = "content",\n',
        "    mode: Annotated[\n        str,\n        Field(\n            description=(\n"
        '                "with_content: matched lines+context (default); ranked_map: ranked file pointers; "\n'
        '                "paths_only: matching file paths; count_only: path + match count. "\n'
        '                "Aliases like file_paths_with_content are also accepted."\n'
        '            )\n        ),\n    ] = "with_content",\n',
    )
)

# 5) one-line docstring default mention
edits.append(
    (
        "Search code by regex/glob/type. mode='content' (default) discovers AND reads matched ",
        "Search code by regex/glob/type. mode='with_content' (default) discovers AND reads matched ",
    )
)

# 6) read tool's grep suggestion uses the verbose name -> new canonical
edits.append(
    (
        'holds something, use `grep` with output_mode="file_paths_with_content" to',
        'holds something, use `grep` with mode="with_content" to',
    )
)

for old, new in edits:
    if new.split(chr(34))[1] if False else False:
        pass
    if old in t:
        t = t.replace(old, new, 1)
    elif new in t:
        pass  # already applied
    else:
        print("NOT FOUND:", repr(old[:60]))
        raise SystemExit
open(MCP, "w", encoding="utf-8").write(t)
print("renamed: with_content / ranked_map / paths_only / count_only")
