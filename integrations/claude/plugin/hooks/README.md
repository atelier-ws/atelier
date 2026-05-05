# Claude Hook Notes

## Optional PostToolUse Compaction

`post_tool_use_compact.py` is an opt-in PostToolUse hook for large `Read`, `Grep`, and `Bash` outputs. It reads the Claude Code hook payload from stdin, estimates output size, and calls Atelier's `compact()` capability when the output is above the configured threshold.

The hook is fail-open: malformed payloads, missing Python dependencies, or unavailable compaction support exit with status 0 and no output.

To opt in, copy the `PostToolUse` block from `integrations/claude/plugin/settings.json.example` into your Claude Code settings for this plugin.

Thresholds are configured in the active Atelier root:

```toml
[compact]
threshold_tokens = 500
budget_tokens = 400
```

Hook responses include both `toolOutput` and `hookSpecificOutput.additionalContext` fields so hook runners can either replace the visible output or append the compacted result. Every compacted response includes a recovery hint for re-fetching the original output.
