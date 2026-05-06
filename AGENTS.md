# Agent Reasoning Runtime — Codex instructions

You are coding inside the `atelier/` reasoning runtime, or a repo that has it wired in via MCP. Follow this loop.

## Before editing code

1. Call `reasoning` with:
   - `task`: the user request, in one sentence
   - `files`: the files you are likely to touch
   - `domain`: optional, e.g. `coding`, `beseam.shopify.publish`
   - `errors`: any known error messages
2. Read every returned procedure. They are short on purpose.
3. Draft a plan as a list of concrete steps.
4. Call `lint` with the same task/files plus your `plan`.
   - If the result is `blocked`, **do not edit files**. Apply `suggested_plan` and re-check.
   - If the result is `warn`, address each warning in the next plan revision.

## During work

- If the same test or command fails twice with the same error, call `rescue` with the error text. Do not run that command a third time first.
- Never store hidden reasoning anywhere. The runtime stores only observable facts.

## After finishing

1. Call `trace` with the observable summary:
   - `agent`: `"codex"`
   - `status`: `success` | `failed` | `partial`
   - `files_touched`, `commands_run`, `errors_seen`
   - `diff_summary` (one sentence)
   - `validation_results`: list of `{name, passed, detail}` entries
2. For high-risk domains (`beseam.shopify.publish`, `beseam.pdp.schema`, `beseam.catalog.fix`, `beseam.tracker.classification`) also call `verify` with the rubric id for the domain.

## Hard rules

- Do not ignore `high`-severity Reasoning Runtime warnings.
- Do not store secrets, API keys, tokens, or hidden chain-of-thought in traces.
- Do not bypass the plan checker by inlining edits without first running it.

## MCP wiring

In your Codex MCP config:

```json
{
  "mcpServers": {
    "atelier": {
      "command": "uv",
      "args": ["run", "atelier-mcp"],
      "cwd": "/path/to/repo/atelier",
      "env": { "ATELIER_ROOT": ".atelier" }
    }
  }
}
```

The MCP server exposes exactly: `reasoning`, `lint`, `route`, `rescue`, `trace`, `verify`, `memory`, `read`, `edit`, `search`, `compact`, and `atelier_repo_map`.
