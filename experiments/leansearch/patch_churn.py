"""Add the edit-test-fail churn detector + wire it at the convergence hook."""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
SNIP = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch/churn_snippet.py"

snippet = open(SNIP, encoding="utf-8").read().rstrip() + "\n"
t = open(MCP, encoding="utf-8").read()

if "_test_churn_intervention" in t:
    print("churn detector already present")
else:
    # 1) insert the new functions right after _convergence_intervention
    anchor1 = '    return f"{response_text}\\n\\n[atelier] {decision}"  # nudge\n'
    if anchor1 not in t:
        print("anchor1 (end of _convergence_intervention) NOT FOUND")
        raise SystemExit
    t = t.replace(anchor1, anchor1 + snippet, 1)
    # 2) wire the hook right after the _convergence_intervention call
    anchor2 = "                    response_text = _convergence_intervention(name, _spill_args, response_text)\n"
    if anchor2 not in t:
        print("anchor2 (convergence hook call) NOT FOUND")
        raise SystemExit
    t = t.replace(
        anchor2,
        anchor2 + "                    response_text = _test_churn_intervention(name, _spill_args, response_text)\n",
        1,
    )
    open(MCP, "w", encoding="utf-8").write(t)
    print("churn detector inserted + hooked")
