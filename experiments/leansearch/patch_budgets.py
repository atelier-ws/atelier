"""web_fetch 2K->8K (dispatch); per-command bash stdout tiers (handler compaction):
listings lean (2K), test runs keep more failures (8K), generic unchanged (6K).
"""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
BASH = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/core/capabilities/tool_supervision/bash_exec.py"

# --- 1) web_fetch inline budget 2K -> 8K ---
m = open(MCP, encoding="utf-8").read()
old_map = '_SPILL_RESULT_CHARS_BY_TOOL = {"bash": 8 * 1024, "read": 16 * 1024}'
new_map = '_SPILL_RESULT_CHARS_BY_TOOL = {"bash": 8 * 1024, "read": 16 * 1024, "web_fetch": 8 * 1024}'
if '"web_fetch": 8 * 1024' in m:
    print("web_fetch budget already set")
elif old_map in m:
    open(MCP, "w", encoding="utf-8").write(m.replace(old_map, new_map, 1))
    print("web_fetch budget 2K -> 8K")
else:
    print("MCP map NOT FOUND")
    raise SystemExit

# --- 2) per-command bash stdout tiers in _compact_result ---
b = open(BASH, encoding="utf-8").read()
helper = '''

# Per-command-kind stdout budgets. Bare listings (ls/tree/du/git status ...) are
# enumerations -- mostly noise -- so they get a lean cap; test runs keep more
# (failures are the actionable signal, and truncating them forces a costly
# re-run); everything else keeps the default head+tail cap.
_BASH_LISTING_RE = re.compile(
    r"^\\s*(?:cd\\s+[^&|;]+&&\\s*)?(?:ls|tree|du|df|find|stat|env|printenv|ps"
    r"|git\\s+status|git\\s+ls-files|git\\s+branch)\\b",
    re.IGNORECASE,
)
_BASH_LISTING_CHAR_CAP = 2000
_BASH_TEST_CHAR_CAP = 8000


def _bash_output_budget(command: str) -> int:
    """Stdout char budget keyed by command kind (test / listing / generic)."""
    if _TEST_CMD_RE.search(command):
        return _BASH_TEST_CHAR_CAP
    if _BASH_LISTING_RE.search(command):
        return _BASH_LISTING_CHAR_CAP
    return _BASH_STDOUT_CHAR_CAP
'''
anchor = "def _compact_result("
if "_bash_output_budget" in b:
    print("bash tiers already present")
else:
    i = b.find(anchor)
    if i == -1:
        print("_compact_result NOT FOUND")
        raise SystemExit
    b = b[:i] + helper.lstrip("\n") + "\n\n" + b[i:]
    # wire the budget into the compaction body
    old_body = (
        "    clean_stdout = _strip_ansi(raw_stdout)\n"
        "    if _TEST_CMD_RE.search(command):\n"
        "        compact = _extract_test_output(clean_stdout)\n"
        "        stdout_omitted = 0\n"
        "        stdout_chars = max(0, len(clean_stdout) - len(compact))\n"
        "        stdout_compact = compact\n"
        "    else:\n"
        "        stdout_compact, stdout_omitted, stdout_chars = _head_tail_lines(clean_stdout.splitlines(), head, tail)\n"
        "        capped = _cap_chars(stdout_compact, _BASH_STDOUT_CHAR_CAP)\n"
    )
    new_body = (
        "    clean_stdout = _strip_ansi(raw_stdout)\n"
        "    budget = _bash_output_budget(command)\n"
        "    if _TEST_CMD_RE.search(command):\n"
        "        compact = _extract_test_output(clean_stdout, max_chars=budget)\n"
        "        stdout_omitted = 0\n"
        "        stdout_chars = max(0, len(clean_stdout) - len(compact))\n"
        "        stdout_compact = compact\n"
        "    else:\n"
        "        stdout_compact, stdout_omitted, stdout_chars = _head_tail_lines(clean_stdout.splitlines(), head, tail)\n"
        "        capped = _cap_chars(stdout_compact, budget)\n"
    )
    if old_body not in b:
        print("compact body NOT FOUND")
        raise SystemExit
    b = b.replace(old_body, new_body, 1)
    open(BASH, "w", encoding="utf-8").write(b)
    print("bash per-command tiers wired (listing 2K / test 8K / generic 6K)")
