"""Port the known-bad redirects (bash_exec) + the code_search desc fix to the worktree."""

BASH = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/core/capabilities/tool_supervision/bash_exec.py"
MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
SNIP = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch/redirect_snippet.py"

helper = open(SNIP, encoding="utf-8").read().rstrip() + "\n\n\n"
classify_anchor = (
    "def classify_command(command: str, *, allowed_write_roots: list[Path] | None = None) -> CommandPolicyDecision:"
)
call_old = (
    "    for segment in _split_command_segments(command):\n"
    "        blocked = _block_check_segment(segment)\n"
    "        if blocked is not None:\n"
    "            return blocked\n\n"
    "    try:\n"
    "        tokens = shlex.split(command)\n"
)
call_new = (
    "    for segment in _split_command_segments(command):\n"
    "        blocked = _block_check_segment(segment)\n"
    "        if blocked is not None:\n"
    "            return blocked\n\n"
    "    bad = _redirect_known_bad(command)\n"
    "    if bad is not None:\n"
    "        return bad\n\n"
    "    try:\n"
    "        tokens = shlex.split(command)\n"
)

t = open(BASH, encoding="utf-8").read()
if "_redirect_known_bad" in t:
    print("bash_exec already patched")
elif classify_anchor in t and call_old in t:
    t = t.replace(classify_anchor, helper + classify_anchor, 1).replace(call_old, call_new, 1)
    open(BASH, "w", encoding="utf-8").write(t)
    print("bash_exec: redirects added")
else:
    print("bash_exec NOT FOUND -- anchor:", classify_anchor in t, "call:", call_old in t)

desc_old = (
    '        "Search the indexed codebase for implementations, symbols, references, "\n'
    '        "call flow, or relevant source. Use instead of bash, grep, or rg when "\n'
    '        "locating code. Returns source grouped by file plus callers, callees, "\n'
    '        "usages, and blast radius. Treat returned source as already read. "\n'
    '        "Use read when the exact file or symbol is already known."'
)
desc_new = (
    '        "Search the indexed codebase for code. Returns relevant source grouped by "\n'
    '        "file, plus `related_symbols` (every relevant definition across files, with "\n'
    '        "locations) and `candidate_files`. Use instead of grep/find. Treat returned "\n'
    '        "source as already read; use `read` only for a file it did not return."'
)
m = open(MCP, encoding="utf-8").read()
if "related_symbols` (every relevant definition" in m:
    print("mcp_server desc already fixed")
elif desc_old in m:
    open(MCP, "w", encoding="utf-8").write(m.replace(desc_old, desc_new, 1))
    print("mcp_server: code_search desc fixed")
else:
    print("mcp_server desc NOT FOUND")
