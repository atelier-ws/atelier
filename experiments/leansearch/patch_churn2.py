"""Churn classifier: a test-ish run with NO pass marker (custom repro.py printing
its own diagnostics) is not confirmed progress -> count as no-pass, so a repeated
repro spiral (django-13344) builds the streak instead of slipping past.
"""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
t = open(MCP, encoding="utf-8").read()
old = '    if _TEST_PASS_RE.search(text or ""):\n        return "PASS"\n    return None\n'
new = (
    '    if _TEST_PASS_RE.search(text or ""):\n'
    '        return "PASS"\n'
    "    # A test-ish run with neither marker (e.g. a custom repro.py printing its own\n"
    "    # diagnostics) is NOT confirmed progress -- treat as no-pass so a repeated repro\n"
    "    # spiral builds the streak instead of slipping past the detector.\n"
    '    return "FAIL"\n'
)
if "# A test-ish run with neither marker" in t:
    print("already patched")
elif old in t:
    open(MCP, "w", encoding="utf-8").write(t.replace(old, new, 1))
    print("ambiguous test-ish run -> no-pass (counts toward streak)")
else:
    print("ANCHOR NOT FOUND")
    raise SystemExit
