"""Redirected bash calls inherit the TARGET tool's spill budget/semantics, not
bash's. sed -n/cat -> read (16KB, incremental-retrieval), curl -> web_fetch (its
own lean cap). grep/find stay on the bash backstop (already bounded in-handler).
Embodies 'spill config per call type' as one pure function.
"""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
t = open(MCP, encoding="utf-8").read()

helper = '''

# Redirected bash calls (curl->web_fetch, sed -n / cat -> read) take the TARGET
# tool's spill identity, not bash's -- a redirected read keeps read's larger
# incremental-retrieval budget; a redirected fetch keeps web_fetch's lean cap.
# grep/find_glob bound their own output in-handler (ranked projection / 300-entry
# cap) so they keep the generic bash backstop.
_REWRITE_SPILL_IDENTITY = {
    "read": "read",
    "read_range": "read",
    "web_fetch": "web_fetch",
}


def _effective_spill_tool(tool_name: str, args: dict[str, Any]) -> str:
    """Spill identity for a call: a bash command rewritten to another tool spills
    AS that tool (its budget + semantics); everything else spills as itself."""
    if tool_name != "bash":
        return tool_name
    command = str(args.get("command") or "").strip() if isinstance(args, dict) else ""
    if not command:
        return tool_name
    try:
        from atelier.core.capabilities.tool_supervision.bash_exec import classify_command

        decision = classify_command(command)
    except Exception:  # noqa: BLE001 -- spill identity must never raise
        return tool_name
    if decision.action == "rewrite" and decision.rewrite_target:
        return _REWRITE_SPILL_IDENTITY.get(decision.rewrite_target, tool_name)
    return tool_name
'''

anchor = '_SPILL_CHAR_CAP_TOOLS = frozenset({"bash", "sql", "web_fetch", "read"})\n'
if "_effective_spill_tool" in t:
    print("helper already present")
elif anchor in t:
    t = t.replace(anchor, anchor + helper, 1)
    print("helper added")
else:
    print("ANCHOR NOT FOUND")
    raise SystemExit

old_call = (
    "                response_text = _spill_oversized_result_text(\n"
    "                    response_text,\n"
    "                    name,\n"
    "                    _spill_args,\n"
    "                    _spill_result_chars(name),\n"
    '                    unit="chars",\n'
    "                    tools=_SPILL_CHAR_CAP_TOOLS,\n"
    "                )\n"
)
new_call = (
    "                _eff_spill_tool = _effective_spill_tool(name, _spill_args)\n"
    "                response_text = _spill_oversized_result_text(\n"
    "                    response_text,\n"
    "                    _eff_spill_tool,\n"
    "                    _spill_args,\n"
    "                    _spill_result_chars(_eff_spill_tool),\n"
    '                    unit="chars",\n'
    "                    tools=_SPILL_CHAR_CAP_TOOLS,\n"
    "                )\n"
)
if "_eff_spill_tool" in t and "_eff_spill_tool = _effective_spill_tool" in t:
    print("dispatch already patched")
elif old_call in t:
    t = t.replace(old_call, new_call, 1)
    print("dispatch char-spill now uses effective tool")
else:
    print("DISPATCH BLOCK NOT FOUND")
    raise SystemExit

open(MCP, "w", encoding="utf-8").write(t)
print("done")
