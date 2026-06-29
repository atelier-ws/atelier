"""Replace the worktree's soft nudge with the escalating intervention."""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
SNIP = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch/escalation_snippet.py"

new_helper = open(SNIP, encoding="utf-8").read().rstrip() + "\n"

# The old nudge helper block, from its leading comment to the end of the function.
old_start = "# Convergence nudge: the top remaining cost sink is tasks that SPIRAL"
old_end = '            "the failing test and the code you have already seen."\n        )\n    return ""\n'

call_old = (
    "                with contextlib.suppress(Exception):\n"
    "                    _nudge_text = _convergence_nudge(name)\n"
    "                    if _nudge_text:\n"
    "                        response_text = response_text + _nudge_text\n"
)
call_new = (
    "                with contextlib.suppress(Exception):\n"
    "                    response_text = _convergence_intervention(name, _spill_args, response_text)\n"
)

text = open(MCP, encoding="utf-8").read()
if "_convergence_intervention" in text:
    print("already patched")
    raise SystemExit
i = text.find(old_start)
j = text.find(old_end)
if i == -1 or j == -1 or call_old not in text:
    print("NOT FOUND -- start:", i != -1, "end:", j != -1, "call:", call_old in text)
    raise SystemExit
j_end = j + len(old_end)
text = text[:i] + new_helper + text[j_end:]
text = text.replace(call_old, call_new, 1)
open(MCP, "w", encoding="utf-8").write(text)
print("patched: escalating convergence intervention installed")
