# Claude Code integration

Claude Code supports MCP servers + lifecycle hooks (`SessionStart`, `PreToolUse`, `PostToolUse`, `Stop`). Wire the runtime into all four.

## 1. MCP server

`~/.config/claude-code/mcp.json` (or repo-local equivalent):

```json
{
  "mcpServers": {
    "atelier": {
      "command": "uv",
      "args": ["run", "atelier-mcp"],
      "cwd": "/abs/path/to/repo/atelier",
      "env": { "ATELIER_ROOT": ".atelier" }
    }
  }
}
```

## 2. Hooks

Save as `.claude/hooks.json` (or whatever your Claude Code version expects):

```json
{
  "SessionStart": {
    "command": "uv",
    "args": [
      "run",
      "atelier",
      "context",
      "--task",
      "${SESSION_TITLE:-repository session}",
      "--domain",
      "coding"
    ],
    "cwd": "/abs/path/to/repo/atelier",
    "inject_as": "system_message"
  },
  "PreToolUse": {
    "match": { "tool": "Edit" },
    "command": "uv",
    "args": [
      "run",
      "atelier",
      "check-plan",
      "--task",
      "${SESSION_TITLE:-edit}",
      "--step",
      "${TOOL_INPUT_DESCRIPTION}",
      "--file",
      "${TOOL_INPUT_FILE_PATH}",
      "--json"
    ],
    "cwd": "/abs/path/to/repo/atelier",
    "block_on_exit_code": 2
  },
  "PostToolUse": {
    "match": { "tool": "Bash" },
    "when": { "exit_code": "non_zero" },
    "command": "uv",
    "args": [
      "run",
      "atelier",
      "rescue",
      "--task",
      "${SESSION_TITLE:-debug}",
      "--error",
      "${TOOL_OUTPUT_LAST_LINE}",
      "--json"
    ],
    "cwd": "/abs/path/to/repo/atelier"
  },
  "Stop": {
    "command": "bash",
    "args": [
      "-c",
      "echo '${SESSION_SUMMARY_JSON}' | uv run atelier record-trace"
    ],
    "cwd": "/abs/path/to/repo/atelier"
  }
}
```

Field names depend on your Claude Code version. The contract is:

- **SessionStart**: inject `atelier context` output as a system message.
- **PreToolUse / Edit**: run `atelier check-plan`. Exit code `2` blocks the edit.
- **PostToolUse / Bash (failed)**: run `atelier rescue`, surface the suggestion.
- **Stop**: feed an observable summary into `atelier record-trace`.

## 3. Smoke test

After wiring, ask Claude to "rename Shopify product by URL handle". The PreToolUse hook should call `check-plan`, get a `blocked` result, and prevent the edit.

## 4. Hard rules (mirror these in `CLAUDE.md`)

- Never bypass a `blocked` plan check by editing files anyway.
- Never include hidden chain-of-thought in `record_trace` payloads — only observable facts.
- For high-risk domains, call `run_rubric_gate` before declaring success.
