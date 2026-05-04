# Atelier Docs

Atelier is a reasoning and procedure runtime for AI agents. Not memory. Not a vector DB.
A structured procedure store that agents query before and after complex tasks.

## By Audience

### First Time Here

| Doc                                | What it covers                                      |
| ---------------------------------- | --------------------------------------------------- |
| [quickstart.md](quickstart.md)     | 5-minute tutorial: init, check-plan, trace, extract |
| [installation.md](installation.md) | Requirements, backends, env vars                    |

### Connecting an Agent Host

| Doc                                                                      | Host                        |
| ------------------------------------------------------------------------ | --------------------------- |
| [hosts/claude-code.md](hosts/claude-code.md)                             | Claude Code (Anthropic)     |
| [hosts/copilot.md](hosts/copilot.md)                                     | VS Code Copilot             |
| [hosts/codex.md](hosts/codex.md)                                         | Codex CLI (OpenAI)          |
| [hosts/opencode.md](hosts/opencode.md)                                   | opencode                    |
| [hosts/gemini-cli.md](hosts/gemini-cli.md)                               | Gemini CLI (Google)         |
| [copy-paste/copilot-instructions.md](copy-paste/copilot-instructions.md) | Copilot instructions (no MCP)|

→ Full matrix: [integrations/host-matrix.md](integrations/host-matrix.md)

### Understanding the CLI

| Doc              | What it covers                                   |
| ---------------- | ------------------------------------------------ |
| [cli.md](cli.md) | Full command reference, exit codes, trace schema |

### Configuration Bundles

| Doc                  | What it covers                              |
| -------------------- | ------------------------------------------- |
| [packs.md](packs.md) | Bundle format, CLI commands, local-only     |

### Authoring Content

| Doc                                                                            | What it covers               |
| ------------------------------------------------------------------------------ | ---------------------------- |
| [authoring/reasonblock-authoring.md](authoring/reasonblock-authoring.md)       | ReasonBlock format           |
| [authoring/rubric-authoring.md](authoring/rubric-authoring.md)                 | Rubric format                |
| [authoring/environment-authoring.md](authoring/environment-authoring.md)       | Environment format           |
| [authoring/failure-cluster-authoring.md](authoring/failure-cluster-authoring.md) | Failure cluster format     |

### Engineering & Architecture

| Doc                                                                                                       | What it covers                                                  |
| --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| [architecture/runtime.md](architecture/runtime.md)                                                        | Runtime diagram, components, interfaces                         |
| [architecture/cost-performance-runtime.md](architecture/cost-performance-runtime.md)                      | Quality-aware routing, context budgeting, verification, evals    |
| [architecture/IMPLEMENTATION_PLAN_V2.md](architecture/IMPLEMENTATION_PLAN_V2.md)                          | **V2 plan**: stateful memory, ReasonBlocks evolution, ≥50% context savings |
| [architecture/IMPLEMENTATION_PLAN_V2_DATA_MODEL.md](architecture/IMPLEMENTATION_PLAN_V2_DATA_MODEL.md)    | V2 data model — Pydantic + SQL DDL                             |
| [architecture/work-packets/INDEX.md](architecture/work-packets/INDEX.md)                                  | V2 work-packets — atomic units for subagents                   |
| [engineering/storage.md](engineering/storage.md)                 | SQLite vs PostgreSQL, schema, backups                |
| [engineering/service.md](engineering/service.md)                 | HTTP service, all endpoints, auth                    |
| [engineering/mcp.md](engineering/mcp.md)                         | MCP server, all tools, remote mode                   |
| [engineering/security.md](engineering/security.md)               | Threat model, controls, OWASP checklist              |
| [engineering/evals.md](engineering/evals.md)                     | Eval system, benchmark, lifecycle                    |
| [engineering/contributing.md](engineering/contributing.md)       | Dev setup, style, PR guidelines                      |
| [production-readiness.md](production-readiness.md)               | Production deployment and operations checklist       |

### Operations

| Doc                                                | What it covers         |
| -------------------------------------------------- | ---------------------- |
| [troubleshooting.md](troubleshooting.md)           | Known issues and fixes |
| [engineering/service.md](engineering/service.md)   | HTTP service ops       |
| [engineering/security.md](engineering/security.md) | Auth, redaction, OWASP |

## Quick Reference

```bash
cd atelier && uv sync --all-extras
uv run atelier init
uv run atelier check-plan --task "..." --domain "..." --step "..."
uv run atelier record-trace < trace.json
uv run atelier extract-block TRACE_ID
uv run atelier run-rubric RUBRIC_ID
```

```bash
make install   # Install deps, host integrations, status helper, runtime store
make verify    # Code checks, runtime smoke tests, host integration checks
make demo      # Run the blocked-plan demo
make help      # Show all targets
```
