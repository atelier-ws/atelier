"""Set the atelier:auto persona to the validated lean+bulk config (best so far).

Rebuilds from main's pristine auto.md, then replaces the two soft bullets with
the bulk/no-sequential directive and leads with code_search. (The minimal-turn
+ tool-drop variant backfired under n=1 variance, so we keep the cleaner one.)
Idempotent. Edits the worktree copy mounted in-container.
"""
MAIN = "/home/pankaj/Projects/leanchain/atelier/integrations/claude/plugin/agents/auto.md"
AUTO = "/home/pankaj/Projects/leanchain/atelier-leansearch/integrations/claude/plugin/agents/auto.md"

NEW_EFFICIENT = (
    "- **Bulk, never sequential.** Read every file and line-range you need in ONE "
    "`read` call (pass them all in `files[]`); never read the same file twice. Make "
    "ALL edits — within a file and across files — in ONE `edit` call's `edits[]` array. "
    "A sequential read→edit→read→edit loop is the main waste: one `code_search`, one "
    "bulk `read` for anything it didn't return, then one bulk `edit`. Keep output to "
    "what changes the next action."
)
NEW_LEAD = (
    "- **Fewest calls to the answer.** Lead with `code_search` — it returns the relevant "
    "symbols' source grouped by file in one call (treat it as already read; do NOT "
    "re-`read` what it returned). Go straight to one bulk `edit`; only `read` for a "
    "file `code_search` did not return, batching those reads into a single call."
)


def main():
    text = open(MAIN, encoding="utf-8").read()
    out, did_eff, did_lead = [], False, False
    for ln in text.splitlines(keepends=True):
        if ln.startswith("- **Efficient by default.**"):
            out.append(NEW_EFFICIENT + "\n"); did_eff = True
        elif ln.startswith("- **Fewest calls to the answer.**"):
            out.append(NEW_LEAD + "\n"); did_lead = True
        else:
            out.append(ln)
    open(AUTO, "w", encoding="utf-8").write("".join(out))
    print(f"applied (efficient={did_eff}, lead={did_lead})")


if __name__ == "__main__":
    main()
