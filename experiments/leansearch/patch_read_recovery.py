"""read(files=[F], symbol=S) recovery: the model means 'symbol S as defined in file F'
(AND) -- the most precise read it can ask for. Resolve the symbol scoped to the file
instead of erroring 'provide either files or symbol' and burning a turn.
"""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
t = open(MCP, encoding="utf-8").read()
old = (
    "    if files is not None and symbol is not None:\n"
    '        raise ValueError("provide either files or symbol, not both")\n'
)
new = (
    "    if files is not None and symbol is not None:\n"
    "        # Recovery (don't reject): both given means 'this symbol AS DEFINED IN this\n"
    "        # file' -- the most precise read the model can ask for. Resolve the symbol\n"
    "        # scoped to the given file instead of costing a turn on a validation error.\n"
    "        _scope_path: str | None = None\n"
    "        if files:\n"
    "            _first = files[0]\n"
    "            if isinstance(_first, str):\n"
    "                _scope_path = _split_file_opts(_first)[0] or None\n"
    "            elif isinstance(_first, dict):\n"
    '                _scope_path = str(_first.get("path") or "") or None\n'
    "        if isinstance(symbol, list):\n"
    '            return {"symbols": [_op_node(**_parse_symbol(s), path=_scope_path) for s in symbol]}\n'
    "        return _op_node(**_parse_symbol(symbol), path=_scope_path)\n"
)
if "Recovery (don't reject): both given" in t:
    print("already patched")
elif old in t:
    open(MCP, "w", encoding="utf-8").write(t.replace(old, new, 1))
    print("read both-args -> symbol scoped to file (AND recovery)")
else:
    print("ANCHOR NOT FOUND")
    raise SystemExit
