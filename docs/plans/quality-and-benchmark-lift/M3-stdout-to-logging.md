# M3 — Replace stray `print()` with logging

> Risk: Low, but MCP stdio correctness is critical. 132 sites. Depends on M1.

## Problem

132 `print()` calls live in `src/`. The MCP stdio server communicates over
stdout — any stray print there corrupts JSON-RPC framing and can break the
Claude/Codex/Gemini integration. Background services also need structured logs,
not prints.

## Scope

In:
- **MCP/server/background modules**: zero tolerance — every `print()` becomes a
  logger call (or goes to stderr if it's truly user-facing diagnostic).
- **Library/core/infra modules**: convert to module loggers.

Out / careful:
- **CLI (`gateway/cli/`)**: `print()`/`click.echo` to stdout is legitimate user
  output. Prefer `click.echo`. Scope the `T20` rule to *exclude* the CLI
  package, or use `per-file-ignores` for it, so user-facing output isn't
  flagged. Confirm the chosen approach matches M1's `T20` config.

## Files

```bash
grep -rln "print(" src --include='*.py'
```
Classify each file: CLI (allowed) vs MCP/server/core/infra (convert).

## Steps

1. List offending files; bucket into CLI vs non-CLI.
2. For non-CLI files: add/confirm a module logger, convert each `print()` to the
   appropriate level (`debug`/`info`/`warning`). Diagnostics that must reach a
   user on a TTY go to `stderr`, never stdout, in server contexts.
3. For CLI files: switch raw `print()` to `click.echo` where not already, and
   ensure `T20` is scoped to ignore the CLI package (coordinate with M1).
4. Remove fixed non-CLI files from any `T20` `per-file-ignores`.

## Validation

```bash
make lint && make typecheck && make test
# MCP stdio framing smoke: server must emit nothing on stdout except protocol
uv run pytest tests/gateway/test_mcp_tool_handlers.py tests/gateway/test_p0_mcp_surfaces.py -q
```
Manually smoke the MCP server start and confirm no banner/log leaks to stdout.

## Done when

- No `print()` to stdout in MCP/server/background/core/infra modules.
- CLI user output preserved via `click.echo`; `T20` enforced everywhere except
  the CLI package.
