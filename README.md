# Atelier

**Agent Context Runtime** — reusable procedures, failure rescue, context compression,
and cross-vendor routing for coding agents.

Atelier is an MCP server + SDK middleware that plugs into Claude Code, Codex CLI,
Copilot, opencode, Antigravity, Cursor, Hermes, and any MCP-compatible host.
It gives agents shared context memory, model routing, tool supervision, loop
detection, lesson promotion, and a savings-optimized execution layer.

---

## Install

Requires Python ≥ 3.11 and `uv`:

```bash
curl -fsSL https://atelier.beseam.com/install.sh | bash
```

Or from source:

```bash
uv sync --all-extras
atelier init
```

## What runs after install

| Surface | Description |
|---------|-------------|
| `atelier` CLI | `atelier tools call …`, `atelier sessions …`, `atelier memory …` |
| MCP server | `atelier-mcp` — exposes tools to any MCP host |
| Background service | `atelier background` — daemon for sync, telemetry, monitors |

## Quick start

```bash
# Check installation
atelier --version

# See available tools
atelier tools list

# Run a task with context reuse and failure rescue
atelier tools call context --args '{"task":"explain this codebase"}'

# Start the background service
atelier background start

# Open the dashboard (port 3125)
atelier stack up
```

## Supported hosts

Claude Code · Codex CLI · Copilot · opencode · Antigravity · Cursor IDE · Hermes Agent

## License

Apache 2.0

---

## Repository layout

```
atelier/
├── src/atelier/          # Runtime: core capabilities, infrastructure, gateway
├── frontend/             # Dashboard UI (React + Vite)
├── integrations/         # Host plugins, hooks, agent skills
├── benchmarks/           # SWE-bench, MCP tool benchmarks, terminal bench
├── tests/                # Python test suite
├── docs/                 # Architecture, agent OS, product docs
├── scripts/              # Install, verify, and tooling scripts
├── docs-site/            # Docusaurus documentation site
├── deploy/               # Docker, OpenTelemetry, service configs
├── examples/             # SDK usage examples
└── templates/            # Reasonblock project templates (Python, etc.)
```
