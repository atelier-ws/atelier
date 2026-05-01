# Atelier — Gemini CLI plugin

Connects the [Gemini CLI](https://github.com/google-gemini/gemini-cli) to Atelier's MCP server so Gemini can read reasoning blocks, plans, traces, and rubrics.

## Install

1. Make sure the `atelier-mcp` console script is available (run `make install` from `atelier/`, or `LOCAL=1 uv run --project atelier atelier-mcp --help`).
2. Merge the `mcpServers` block from [`settings.json`](./settings.json) into your `~/.gemini/settings.json` (create the file if it does not exist).
3. Set `ATELIER_STORE_ROOT` to the workspace `.atelier/` directory you want Gemini to read.
4. Restart Gemini CLI and run `/mcp list` — you should see `atelier` listed as a connected server.

## Verify

```bash
gemini --prompt "List the current Atelier plans and tell me which ones are stale."
```

If Gemini returns the plan list from `<ATELIER_STORE_ROOT>/plans/`, the plugin is wired correctly.

## Files

- `settings.json` — template fragment to merge into `~/.gemini/settings.json`.
- `verify.sh` — non-destructive smoke test (lists plans, prints the first reasoning block).

## See also

- [`atelier/claude-plugin/`](../claude-plugin/) — Claude Code plugin
- [`atelier/codex-plugin/`](../codex-plugin/) — OpenAI Codex CLI plugin
- [`atelier/copilot/`](../copilot/) — GitHub Copilot (VS Code) MCP config
- [`atelier/opencode/`](../opencode/) — OpenCode MCP config

## V2 tools

Atelier V2 adds nine MCP tools (run-ledger, monitor, compress, two
environment helpers, three smart-tool wrappers) on top of the original
six. All V1 tools remain backward compatible. See
[`atelier/codex-plugin/references/v2-tools.md`](../codex-plugin/references/v2-tools.md)
for the full surface.

Gemini CLI does not register slash commands or sub-agents; the
equivalents are exposed only through MCP and the host CLI
(`atelier savings`, `atelier analyze-failures`, `atelier eval`,
`atelier benchmark`, `atelier tool-mode`).
