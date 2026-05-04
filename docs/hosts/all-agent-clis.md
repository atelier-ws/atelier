# Atelier — All Agent CLI Integrations

Install Atelier into every supported coding agent host in one command:

```bash
make install    # install into all CLIs found on PATH
make verify     # verify code, runtime, and installed hosts
```

---

## Supported Hosts

| Host            | Support Level                              | Advanced installer             |
| --------------- | ------------------------------------------ | ------------------------------ |
| Claude Code     | Full plugin (skills, commands, hooks, MCP) | `scripts/install_claude.sh`    |
| Codex CLI       | Skills + subagents + MCP + wrapper         | `scripts/install_codex.sh`     |
| opencode        | MCP + workspace agent profile              | `scripts/install_opencode.sh`  |
| VS Code Copilot | MCP + instructions + chat mode + tasks     | `scripts/install_copilot.sh`   |
| Gemini CLI      | MCP + custom command presets               | `scripts/install_gemini.sh`    |

---

## Quickstart (install everything at once)

```bash
# 1. Make sure you're in the atelier/ directory
cd atelier

# 2. Install dependencies
uv sync --all-extras

# 3. Install into all available agent CLIs
make install

# 4. Verify
make verify
```

Hosts whose CLIs are not on PATH are skipped gracefully — this is expected in CI.

---

## Behavior Contract

All install scripts:

- Are **idempotent** — safe to run multiple times
- **Back up existing files** before any write (`.atelier-backup.TIMESTAMP`)
- **Skip gracefully** if the host CLI is not on PATH (exit 0)
- Support `--dry-run` (print actions, write nothing)
- Support `--print-only` (print manual steps for offline/audited environments)
- Support `--strict` (exit nonzero if CLI absent — useful for CI gates)
- Support `--workspace PATH` to target a non-cwd workspace

---

## Host-Specific Install Docs

- [claude-code-install.md](claude-code-install.md)
- [codex-install.md](codex-install.md)
- [opencode-install.md](opencode-install.md)
- [copilot-install.md](copilot-install.md)
- [gemini-cli-install.md](gemini-cli-install.md)
- [host-capability-matrix.md](host-capability-matrix.md)

---

## Integrations Layout

Detailed documentation and example configs for each host live in:

```
atelier/integrations/
├── claude/          # Full plugin config
├── codex/           # Skills + MCP example
├── opencode/        # opencode.jsonc example
├── copilot/         # .vscode/mcp.json + copilot-instructions
└── gemini/          # ~/.gemini/settings.json example
```

Each host dir has: `README.md`, example config(s), `install.sh` (→ `scripts/install_<host>.sh`), `verify.sh` (→ `scripts/verify_<host>.sh`).

---

## MCP Transport

All hosts connect via the same wrapper:

```
atelier/scripts/atelier_mcp_stdio.sh
```

This wrapper: locates the atelier repo from its own path, sets `ATELIER_WORKSPACE_ROOT` and `ATELIER_ROOT`, then execs `uv run python -m atelier.gateway.adapters.mcp_server`. All logs go to stderr; never stdout.

## Core Capability Tools

All hosts receive the same capability tools from the MCP server:

- `atelier_reasoning_reuse`
- `atelier_semantic_memory`
- `atelier_loop_monitor`
- `atelier_tool_supervisor`
- `atelier_context_compressor`
- `atelier_smart_search`
- `atelier_smart_read`
- `atelier_smart_edit`
- `atelier_sql_inspect`

---

## Uninstalling

Each host section above (see host-specific docs) has an Uninstall section. No global uninstall command — each host manages its own config location.
