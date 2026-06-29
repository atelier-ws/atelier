"""Replace the worktree's redirect helper (git-blocking version) with the
general-case revision: no git block, curl/wget -> web_fetch with install-chain
awareness, keep find/sed.
"""

BASH = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/core/capabilities/tool_supervision/bash_exec.py"
SNIP = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch/redirect_snippet.py"

new_helper = open(SNIP, encoding="utf-8").read().rstrip()
classify = (
    "def classify_command(command: str, *, allowed_write_roots: list[Path] | None = None) -> CommandPolicyDecision:"
)
old_start = "# Known-bad shell patterns the LLM reaches for"

text = open(BASH, encoding="utf-8").read()
if "_FETCH_SETUP_RE" in text:
    print("already revised")
    raise SystemExit
i = text.find(old_start)
j = text.find(classify)
if i == -1 or j == -1 or i >= j:
    print("NOT FOUND -- start:", i != -1, "classify:", j != -1)
    raise SystemExit
text = text[:i] + new_helper + "\n\n\n" + text[j:]
open(BASH, "w", encoding="utf-8").write(text)
print("redirect helper revised (general-case)")
