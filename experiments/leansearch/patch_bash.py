"""Insert the bash convergence guard into the worktree's mcp_server.py."""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
SNIP = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch/bash_guard_snippet.py"

helper = open(SNIP, encoding="utf-8").read().rstrip() + "\n\n\n"
anchor = '@mcp_tool(\n    name="bash",'
body_old = "    result = _run_bash_tool(\n        command,"
body_new = (
    "    _fb = _archaeology_fallback(command)\n"
    "    if _fb is not None:\n"
    "        return _fb\n"
    "    result = _run_bash_tool(\n        command,"
)

text = open(MCP, encoding="utf-8").read()
if "_archaeology_fallback" in text:
    print("already patched")
elif anchor in text and body_old in text:
    text = text.replace(anchor, helper + anchor, 1).replace(body_old, body_new, 1)
    open(MCP, "w", encoding="utf-8").write(text)
    print("patched: bash convergence guard inserted")
else:
    print("NOT FOUND -- anchor:", anchor in text, "body:", body_old in text)
