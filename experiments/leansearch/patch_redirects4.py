"""Final redirect pass: never block/message -- find -> internal glob, sed -n -> read
range, both executed inline. Replaces the helper + adds two dispatch handlers.
"""

BASH = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/core/capabilities/tool_supervision/bash_exec.py"
MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
SNIP = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch/redirect_snippet.py"

new_helper = open(SNIP, encoding="utf-8").read().rstrip()
classify = (
    "def classify_command(command: str, *, allowed_write_roots: list[Path] | None = None) -> CommandPolicyDecision:"
)
t = open(BASH, encoding="utf-8").read()
if 'rewrite_target="find_glob"' in t:
    print("bash_exec already final")
else:
    i = t.find("# Known-bad shell")
    j = t.find(classify)
    if i == -1 or j == -1 or i >= j:
        print("bash_exec NOT FOUND")
        raise SystemExit
    open(BASH, "w", encoding="utf-8").write(t[:i] + new_helper + "\n\n\n" + t[j:])
    print("bash_exec: find->glob, sed-n->read_range (no blocks)")

anchor = "    # One execution model: every command runs as a managed session;"
handlers = (
    '    if policy.action == "rewrite" and policy.rewrite_target == "find_glob" and policy.rewrite_payload:\n'
    '        _fg_pat = str(policy.rewrite_payload.get("glob") or "*")\n'
    '        _fg_path = str(policy.rewrite_payload.get("path") or ".")\n'
    "        try:\n"
    "            _fg_base = Path(_fg_path) if Path(_fg_path).is_absolute() else (Path(effective_cwd) / _fg_path)\n"
    "            _fg_hits = sorted(str(p.relative_to(_fg_base)) for p in _fg_base.rglob(_fg_pat) if p.is_file())\n"
    "        except Exception:  # noqa: BLE001 -- redirect must never raise\n"
    "            _fg_hits = []\n"
    '        _fg_out = "\\n".join(_fg_hits[:300]) if _fg_hits else "(no files match)"\n'
    "        if len(_fg_hits) > 300:\n"
    '            _fg_out += f"\\n... ({len(_fg_hits) - 300} more)"\n'
    '        return {"stdout": _fg_out, "stderr": "", "exit_code": 0, "truncated": False, "lines_omitted": 0, "duration_ms": 0}\n\n'
    '    if policy.action == "rewrite" and policy.rewrite_target == "read_range" and policy.rewrite_payload:\n'
    '        _rr_spec = str(policy.rewrite_payload.get("spec") or "").strip()\n'
    "        if _rr_spec:\n"
    "            try:\n"
    '                _rr = cast(dict[str, Any], TOOLS["read"]["handler"]({"files": [_rr_spec]}))\n'
    '                _rr_out = _rr.get("content") if isinstance(_rr, dict) else str(_rr)\n'
    "            except Exception as _rr_exc:  # noqa: BLE001\n"
    '                _rr_out = f"[read] {_rr_exc}"\n'
    '            return {"stdout": str(_rr_out or ""), "stderr": "", "exit_code": 0, "truncated": False, "lines_omitted": 0, "duration_ms": 0}\n\n'
)
m = open(MCP, encoding="utf-8").read()
if 'rewrite_target == "find_glob"' in m:
    print("mcp_server already has find_glob/read_range")
elif anchor in m:
    open(MCP, "w", encoding="utf-8").write(m.replace(anchor, handlers + anchor, 1))
    print("mcp_server: find_glob + read_range handlers added")
else:
    print("mcp_server anchor NOT FOUND")
