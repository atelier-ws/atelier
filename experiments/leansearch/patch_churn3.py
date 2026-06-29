"""Decay the churn streak on a pass instead of zeroing it -- a spiral that
intermixes an occasional passing run (django-13344) would otherwise launder its
streak back to 0 and never escalate to tier-2/3."""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
t = open(MCP, encoding="utf-8").read()
old = (
    '    if outcome == "PASS":\n'
    "        _FAILED_TEST_STREAK[0] = 0\n"
    "        _EDITS_SINCE_GREEN[0] = 0\n"
    "        return response_text\n"
)
new = (
    '    if outcome == "PASS":\n'
    "        # Decay, don't zero: a spiral that intermixes an occasional passing run would\n"
    "        # otherwise launder its streak back to 0 and never escalate. Decaying keeps\n"
    "        # sustained no-pass pressure accumulating toward tier-2/3.\n"
    "        _FAILED_TEST_STREAK[0] = max(0, _FAILED_TEST_STREAK[0] - 2)\n"
    "        _EDITS_SINCE_GREEN[0] = 0\n"
    "        return response_text\n"
)
if "Decay, don't zero" in t:
    print("already patched")
elif old in t:
    open(MCP, "w", encoding="utf-8").write(t.replace(old, new, 1))
    print("pass now decays streak by 2 (anti-laundering)")
else:
    print("ANCHOR NOT FOUND")
    raise SystemExit
