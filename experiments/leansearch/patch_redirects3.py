"""Make curl/wget redirect EXECUTE web_fetch inline (rewrite), like grep->grep_tool.
Replaces the worktree redirect helper + adds the web_fetch rewrite handler.
"""

BASH = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/core/capabilities/tool_supervision/bash_exec.py"
MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
SNIP = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch/redirect_snippet.py"

# 1) replace the helper in bash_exec
new_helper = open(SNIP, encoding="utf-8").read().rstrip()
classify = (
    "def classify_command(command: str, *, allowed_write_roots: list[Path] | None = None) -> CommandPolicyDecision:"
)
old_start = "# Known-bad shell patterns the LLM reaches for"
t = open(BASH, encoding="utf-8").read()
if 'rewrite_target="web_fetch"' in t:
    print("bash_exec already has web_fetch rewrite")
else:
    i = t.find(old_start)
    j = t.find(classify)
    if i == -1 or j == -1 or i >= j:
        print("bash_exec NOT FOUND")
        raise SystemExit
    t = t[:i] + new_helper + "\n\n\n" + t[j:]
    open(BASH, "w", encoding="utf-8").write(t)
    print("bash_exec: curl/wget -> web_fetch rewrite")

# 2) add the web_fetch rewrite handler in the mcp_server bash dispatch
anchor = "    # One execution model: every command runs as a managed session;"
handler = (
    '    if policy.action == "rewrite" and policy.rewrite_target == "web_fetch" and policy.rewrite_payload:\n'
    '        _wf_url = str(policy.rewrite_payload.get("url") or "").strip()\n'
    "        if _wf_url:\n"
    "            try:\n"
    "                from atelier.core.capabilities.web_fetch import fetch_url\n"
    "\n"
    "                _wf = fetch_url(_wf_url)\n"
    '                _wf_out = _wf.get("content") if isinstance(_wf, dict) else str(_wf)\n'
    "            except Exception as _wf_exc:  # noqa: BLE001 -- redirect must never raise\n"
    '                _wf_out = f"[web_fetch] {_wf_exc}"\n'
    "            return {\n"
    '                "stdout": str(_wf_out or ""),\n'
    '                "stderr": "",\n'
    '                "exit_code": 0,\n'
    '                "truncated": False,\n'
    '                "lines_omitted": 0,\n'
    '                "duration_ms": 0,\n'
    "            }\n\n"
)
m = open(MCP, encoding="utf-8").read()
if 'rewrite_target == "web_fetch"' in m:
    print("mcp_server already has web_fetch handler")
elif anchor in m:
    open(MCP, "w", encoding="utf-8").write(m.replace(anchor, handler + anchor, 1))
    print("mcp_server: web_fetch rewrite handler added")
else:
    print("mcp_server anchor NOT FOUND")
