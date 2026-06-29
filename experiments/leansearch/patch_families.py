"""Make code_search return the whole symbol family in ONE call.

Root cause of the matplotlib re-search loop: the engine's own score floor
(_EXPLORE_SCORE_FLOOR_FRAC=0.30) drops sibling definitions (e.g. nonsingular on
MaxNLocator/LogLocator/Locator) below 30% of the top hit, and complete_families
is off by default -- so the family never reaches the agent and it re-searches the
term per class. Turn on complete_families + raise budget_tokens so the family's
source actually lands. Idempotent. Patches the worktree file.
"""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"

OLD = "    result = cast(dict[str, Any], engine.tool_explore(query, max_files=max_files, seed_files=seed_files))"
NEW = (
    "    # complete_families surfaces the whole symbol family (a method overridden on\n"
    "    # sibling classes, a name that camelCase tokenization splits) in ONE call, so\n"
    "    # the agent gets every definition it must edit without re-searching the term\n"
    "    # per class; budget_tokens is raised so that family source actually lands. This\n"
    '    # is the "one search returns everything to edit" path for multi-file tasks.\n'
    "    result = cast(\n"
    "        dict[str, Any],\n"
    "        engine.tool_explore(\n"
    "            query,\n"
    "            max_files=max(max_files, 8),\n"
    "            seed_files=seed_files,\n"
    "            complete_families=True,\n"
    "            budget_tokens=4000,\n"
    "        ),\n"
    "    )"
)

text = open(MCP, encoding="utf-8").read()
if "complete_families=True" in text:
    print("already patched")
elif OLD in text:
    open(MCP, "w", encoding="utf-8").write(text.replace(OLD, NEW))
    print("patched: complete_families=True + budget_tokens=4000")
else:
    print("ANCHOR NOT FOUND")
