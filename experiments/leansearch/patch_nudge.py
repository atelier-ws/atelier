"""Insert the convergence nudge into the worktree's mcp_server.py."""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
SNIP = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch/nudge_snippet.py"

helper = open(SNIP, encoding="utf-8").read().rstrip() + "\n\n\n"
anchor = '_HEAVY_TOOLS = frozenset({"bash", "run", "edit", "web_fetch", "workflow", "agent"})'
call_old = "                response_text = _truncate_result_text(response_text, _max_result_bytes())\n"
call_new = (
    call_old
    + "                with contextlib.suppress(Exception):\n"
    + "                    _nudge_text = _convergence_nudge(name)\n"
    + "                    if _nudge_text:\n"
    + "                        response_text = response_text + _nudge_text\n"
)

text = open(MCP, encoding="utf-8").read()
if "_convergence_nudge" in text:
    print("already patched")
elif anchor in text and call_old in text:
    text = text.replace(anchor, helper + anchor, 1).replace(call_old, call_new, 1)
    open(MCP, "w", encoding="utf-8").write(text)
    print("patched: convergence nudge inserted")
else:
    print("NOT FOUND -- anchor:", anchor in text, "call:", call_old in text)
