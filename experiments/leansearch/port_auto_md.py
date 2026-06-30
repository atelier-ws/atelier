"""Port the generalized (non-benchmark-specific) 'Don't thrash' bullet into the
worktree's canonical mode doc, so the benchmark build's guidance matches the new
generic history-archaeology detector.
"""

from pathlib import Path

p = Path("/home/pankaj/Projects/leanchain/atelier-leansearch/integrations/agents/auto.md")
s = p.read_text()
old = (
    "- **Don't thrash or mine history.** Don't reformulate the same search; don't "
    "`git log` / `git show` / `git blame` to find the upstream fix. If you can't "
    "converge, re-read the failing test and the symbol under test, then edit."
)
new = (
    "- **Don't thrash.** Don't re-run equivalent searches or spiral into history "
    "archaeology hunting for an answer. When you can't converge, stop gathering: "
    "re-read the code under change and whatever defines its expected behavior "
    "(test, caller, or spec), name the root cause in one line, then edit."
)
if new in s:
    raise SystemExit("already ported")
if s.count(old) != 1:
    raise SystemExit(f"old bullet count={s.count(old)} (expected 1)")
p.write_text(s.replace(old, new, 1))
print("auto.md ported in worktree")
