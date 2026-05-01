# Atelier Host Integrations

Canonical adapter configs and install/verify scripts for every supported agent CLI.

## Supported Hosts

| Host            | Dir         | Support level      | Install script        |
| --------------- | ----------- | ------------------ | --------------------- |
| Claude Code     | `claude/`   | Full plugin        | `claude/install.sh`   |
| Codex           | `codex/`    | Skills + MCP       | `codex/install.sh`    |
| opencode        | `opencode/` | MCP config         | `opencode/install.sh` |
| VS Code Copilot | `copilot/`  | MCP + instructions | `copilot/install.sh`  |
| Gemini CLI      | `gemini/`   | MCP config         | `gemini/install.sh`   |

## Quick Install

From the `atelier/` directory:

```bash
# Install into all available agent CLIs (gracefully skips missing ones)
make install-agent-clis

# Verify all integrations
make verify-agent-clis
```

## Per-host

```bash
make install-claude    && make verify-claude
make install-codex     && make verify-codex
make install-opencode  && make verify-opencode
make install-copilot   && make verify-copilot
make install-gemini    && make verify-gemini
```

## Installer contract

- **Idempotent** — safe to run multiple times
- **Backup first** — creates timestamped backup before overwriting any user file
- **Skip if CLI absent** — prints install hint instead of failing
- **`--dry-run`** — print what would happen, touch nothing
- **`--print-only`** — print config snippet only (for manual install)
- **No secrets** — API keys and tokens are never written by install scripts
- **Absolute paths** — configs always use absolute paths, never `~` or `$HOME` in written files

## MCP command (all hosts)

All installers write the same MCP command pointing to the stable wrapper script:

```bash
<atelier_root>/scripts/atelier_mcp_stdio.sh
```

The wrapper locates the atelier repo, sets `ATELIER_ROOT`, and runs:

```
uv run python -m atelier.gateway.adapters.mcp_server
```

Never hardcodes a path; resolves at runtime from the script's own location.
