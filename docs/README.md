# Atelier Docs

Atelier is a reasoning/procedure/runtime layer for AI agents. Not memory. Not a vector DB. A structured procedure store that agents query before and after complex tasks.

## By Audience

### First Time Here

| Doc                                | What it covers                                      |
| ---------------------------------- | --------------------------------------------------- |
| [quickstart.md](quickstart.md)     | 5-minute tutorial: init, check-plan, trace, extract |
| [installation.md](installation.md) | Requirements, backends, env vars                    |

### Connecting an AI Agent Host

| Doc                                                                      | Host                                |
| ------------------------------------------------------------------------ | ----------------------------------- |
| [hosts/claude-code.md](hosts/claude-code.md)                             | Claude Code / Claude (Anthropic)    |
| [hosts/copilot.md](hosts/copilot.md)                                     | GitHub Copilot (VS Code)            |
| [hosts/codex.md](hosts/codex.md)                                         | OpenAI Codex                        |
| [hosts/opencode.md](hosts/opencode.md)                                   | opencode (Sourcegraph)              |
| [hosts/gemini-cli.md](hosts/gemini-cli.md)                               | Gemini CLI (Google)                 |
| [copy-paste/copilot-instructions.md](copy-paste/copilot-instructions.md) | Copilot instructions block (no MCP) |

### Understanding the CLI

| Doc              | What it covers                                   |
| ---------------- | ------------------------------------------------ |
| [cli.md](cli.md) | Full command reference, exit codes, trace schema |

### Pack System

| Doc                  | What it covers                                         |
| -------------------- | ------------------------------------------------------ |
| [packs.md](packs.md) | Pack format, CLI commands, official packs, authoring   |

### Engineering & Architecture

| Doc                                                        | What it covers                                |
| ---------------------------------------------------------- | --------------------------------------------- |
| [engineering/architecture.md](engineering/architecture.md) | System diagram, data models, information flow |
| [engineering/storage.md](engineering/storage.md)           | SQLite vs PostgreSQL, schema, backups         |
| [engineering/service.md](engineering/service.md)           | HTTP service, all endpoints, auth             |
| [engineering/mcp.md](engineering/mcp.md)                   | MCP server, all tools, remote mode            |
| [engineering/workers.md](engineering/workers.md)           | Background workers                            |
| [engineering/security.md](engineering/security.md)         | Threat model, controls, OWASP checklist       |
| [engineering/evals.md](engineering/evals.md)               | Eval system, benchmark, lifecycle             |
| [engineering/dogfooding.md](engineering/dogfooding.md)     | Verified scenarios, expected outputs          |
| [engineering/phase-t-hardening.md](engineering/phase-t-hardening.md) | Phase T1-T6 execution commands and reports |
| [engineering/contributing.md](engineering/contributing.md) | Dev setup, style, PR guidelines               |
| [production-readiness.md](production-readiness.md) | Production deployment and operations checklist |

### Operations / DevOps

| Doc                                                | What it covers          |
| -------------------------------------------------- | ----------------------- |
| [engineering/service.md](engineering/service.md)   | HTTP service deployment |
| [engineering/security.md](engineering/security.md) | Auth, redaction, OWASP  |
| [troubleshooting.md](troubleshooting.md)           | Known issues and fixes  |

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
make verify        # Full gate (must pass before PR)
make demo-all      # Run all demos
make help          # Show all targets
```
