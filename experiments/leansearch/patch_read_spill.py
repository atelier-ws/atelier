"""Let read spill at a HIGH threshold so egregious symbol reads (32k functions)
cap to head+tail + a retrieve reference instead of being re-read as cache_read
every turn. Normal reads (<16KB) are untouched. Idempotent; patches worktree.
"""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"

OLD1 = '_SPILL_RESULT_CHARS_BY_TOOL = {"bash": 8 * 1024}'
NEW1 = '_SPILL_RESULT_CHARS_BY_TOOL = {"bash": 8 * 1024, "read": 16 * 1024}'
OLD2 = '_SPILL_CHAR_CAP_TOOLS = frozenset({"bash", "sql", "web_fetch"})'
NEW2 = '_SPILL_CHAR_CAP_TOOLS = frozenset({"bash", "sql", "web_fetch", "read"})'

text = open(MCP, encoding="utf-8").read()
if '"read": 16 * 1024' in text:
    print("already patched")
elif OLD1 in text and OLD2 in text:
    open(MCP, "w", encoding="utf-8").write(text.replace(OLD1, NEW1, 1).replace(OLD2, NEW2, 1))
    print("patched: read spills at 16KB")
else:
    print("NOT FOUND -- o1:", OLD1 in text, "o2:", OLD2 in text)
