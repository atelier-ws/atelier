"""Second-pass waste hunt across atelier flows: failed/empty tool calls, shell
sub-kinds replaceable by atelier tools, discovery overhead (turns before 1st edit)."""

import glob
import re
import sys
from collections import Counter

sys.path.insert(0, "benchmarks")
from wire_savings._trace_results import largest_request, text_of

flows = sorted(glob.glob(sys.argv[1] + "/*_atelier_rep*.flow"))

failed_edit = empty_grep = errored_shell = 0
shell_kind: Counter = Counter()
total_calls = 0
turns_before_first_edit = []
flow_n = 0

CD_LS = re.compile(r"^\s*(cd |ls |pwd|cat |head |tail |find |echo )")
GIT = re.compile(r"\bgit ")
GREP_SED = re.compile(r"\bgrep \b|\bsed \b|\bawk \b")

for f in flows:
    try:
        j = largest_request(f)
    except Exception:
        j = None
    if not j:
        continue
    flow_n += 1
    calls = 0
    first_edit_at = None
    pending = None  # (name, input) awaiting its tool_result
    for m in j.get("messages") or []:
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                nm = (b.get("name") or "").replace("mcp__plugin_atelier_atelier__", "")
                inp = b.get("input") or {}
                calls += 1
                total_calls += 1
                if nm == "edit" and first_edit_at is None:
                    first_edit_at = calls
                if nm == "shell":
                    cmd = str(inp.get("command") or "")
                    if re.search(r"pytest|runtests|\.test\(", cmd):
                        shell_kind["test"] += 1
                    elif "python -c" in cmd or "python3 -c" in cmd:
                        shell_kind["repl"] += 1
                    elif GIT.search(cmd):
                        shell_kind["git"] += 1
                    elif GREP_SED.search(cmd):
                        shell_kind["grep/sed/awk (atelier grep can do)"] += 1
                    elif CD_LS.search(cmd):
                        shell_kind["cd/ls/cat/find (atelier read/grep can do)"] += 1
                    else:
                        shell_kind["other"] += 1
                pending = (nm, inp)
            elif b.get("type") == "tool_result" and pending:
                res = text_of(b.get("content"))
                nm = pending[0]
                if nm == "edit" and ('"failed":[{' in res or '"failed": [{' in res):
                    failed_edit += 1
                if nm == "grep" and ("(0 files)" in res or '"content":[]' in res or len(res) < 20):
                    empty_grep += 1
                if nm == "shell" and ("exit_code=1" in res or "exit_code=2" in res or "Traceback" in res):
                    errored_shell += 1
                pending = None
    if first_edit_at is not None:
        turns_before_first_edit.append(first_edit_at)

print(f"flows: {flow_n} | total tool calls: {total_calls}")
print("\n=== pure-waste signals ===")
print(f"  failed edits (old_string not found etc): {failed_edit}")
print(f"  empty greps (0 results): {empty_grep}")
print(f"  errored shells (exit!=0 / Traceback): {errored_shell}  (some are intentional test failures)")
print("\n=== shell sub-kinds (which could atelier tools replace?) ===")
for k, c in shell_kind.most_common():
    print(f"  {k:<45} {c}")
if turns_before_first_edit:
    avg = sum(turns_before_first_edit) / len(turns_before_first_edit)
    print(
        f"\n=== discovery overhead ===\n  avg tool-calls before first edit: {avg:.1f}  (min {min(turns_before_first_edit)}, max {max(turns_before_first_edit)})"
    )
