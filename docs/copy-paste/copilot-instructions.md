# Copilot Instructions Block (Copy-Paste)

Use this block if you can't use the MCP server and need to manually inject Atelier's reasoning context into GitHub Copilot Chat or a `.github/copilot-instructions.md` file.

---

## Minimal Block (for `.github/copilot-instructions.md`)

```markdown
## Atelier Reasoning Runtime

Before starting any task in this repository, you MUST follow the Atelier reasoning loop:

1. **Check your plan** — Before editing files, consider whether your plan contains any known dead ends for this domain.

   Known Beseam dead ends (DO NOT USE):
   - "Parse product handle from PDP URL" → use Product GID instead
   - "Lookup product by Shopify handle" → Shopify write APIs require GID

2. **Verify output** — After completing a task in `beseam.shopify.publish` domain, all of the following must be true:
   - `product_identity_uses_gid: true`
   - `pre_publish_snapshot_exists: true`
   - `write_result_checked: true`
   - `post_publish_refetch_done: true`
   - `post_publish_audit_passed: true`
   - `rollback_available: true`

3. **Record what happened** — After each task, state what commands you ran, what errors you saw, and what the outcome was.

If MCP is configured (`atelier` server), use `atelier_check_plan`, `atelier_run_rubric_gate`, and `atelier_record_trace` instead of doing the above manually.
```

---

## Full MCP-Enabled Block

If Copilot Chat has MCP access (configured via `.vscode/mcp.json`), add this to your instructions:

```markdown
## Atelier Reasoning Runtime (MCP)

MCP server `atelier` is available. Use it on every task:

**Before executing:**

1. Call `atelier_get_reasoning_context` with the task + domain
2. Call `atelier_check_plan` with your proposed steps — if it returns `status: blocked`, revise your plan

**After executing:** 3. Call `atelier_run_rubric_gate` with the appropriate rubric and your results 4. Call `atelier_record_trace` with the execution summary

Available rubrics: `rubric_shopify_publish`, `rubric_pdp_audit`, and others (use `atelier_search` to find domain-specific ones).
```

---

## Setup for `.vscode/mcp.json`

```json
&#123;
  "servers": &#123;
    "atelier": &#123;
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--project", "$&#123;workspaceFolder&#125;/atelier", "atelier-mcp"],
      "env": &#123;
        "ATELIER_WORKSPACE_ROOT": "$&#123;workspaceFolder&#125;"
      &#125;
    &#125;
  &#125;
&#125;
```
