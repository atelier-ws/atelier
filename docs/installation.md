# Installation

## Prerequisites

- **Python** ≥ 3.11
- **uv** (package installer) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **npm** (optional, for SCIP code intelligence)

## Quick install

```bash
curl -fsSL https://atelier.beseam.com/install.sh | bash
```

This installs the `atelier` CLI, `atelier-mcp` MCP server, and default agent
configurations for supported hosts.

## Source install

```bash
git clone <repo>
cd atelier
uv sync --all-extras
atelier init
```

## Post-install

```bash
# Verify everything works
atelier --version
atelier tools list

# Start background services (sync, telemetry, monitors)
atelier background start

# Launch the dashboard
atelier stack up
```

## Host-specific installs

Each supported host has its own install script under `integrations/`:

| Host | Command |
|------|---------|
| Claude Code | `bash integrations/claude/install.sh` |
| Codex CLI | `bash integrations/codex/install.sh` |
| Copilot | `bash integrations/copilot/install.sh` |
| opencode | `bash integrations/opencode/install.sh` |
| Antigravity | `bash integrations/antigravity/install.sh` |

## Storage backends

Atelier supports SQLite (default, zero-config) and PostgreSQL/pgvector for
production deployments.
