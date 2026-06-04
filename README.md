# Atelier — Open-Source Context Runtime for Coding Agents

<p align="center">
  <a href="https://github.com/atelier-runtime/atelier/blob/main/LICENSE"><img src="https://img.shields.io/github/license/atelier-runtime/atelier?style=for-the-badge" alt="License" /></a>
  <a href="https://github.com/atelier-runtime/atelier/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/atelier-runtime/atelier/tests.yml?style=for-the-badge&label=tests" alt="Tests" /></a>
  <a href="https://github.com/atelier-runtime/atelier/releases"><img src="https://img.shields.io/github/v/release/atelier-runtime/atelier?style=for-the-badge" alt="Latest release" /></a>
  <a href="https://github.com/atelier-runtime/atelier/releases"><img src="https://img.shields.io/github/downloads/atelier-runtime/atelier/total?style=for-the-badge" alt="Total downloads" /></a>
</p>

**MCP server + SDK middleware that gives every coding agent shared procedures, failure rescue, loop detection, cost tracking, and cross-vendor routing — across Claude Code, Codex, Copilot, LangChain, OpenAI SDK, Gemini ADK, and any MCP host.**

Atelier ships the same context runtime everywhere: CLI, MCP (for all major agent hosts), and background services. It captures what your best engineers know as reusable procedures (ReasonBlocks), learns from recurring failures, validates outputs against domain-specific rubrics, and plugs into any agent host through MCP.

## Install in One Command

```bash
curl -fsSL https://raw.githubusercontent.com/atelier-runtime/atelier/refs/heads/main/scripts/install.sh | bash
```

The installer:

- installs `atelier` (CLI) and `atelier-mcp` (MCP server) as user-level commands in `~/.local/bin`
- initializes the runtime store under `~/.atelier`
- starts the detached `servicectl` background loop (systemd on Linux, launchd on macOS)
- optionally starts the visualization stack when npm is available
- installs supported host integrations when the host CLI is found on `PATH`

Check the installed runtime:

```bash
atelier --version
atelier-mcp --version
atelier background status
```

## What Runs After Install

The installed product gives you **CLI + MCP + Background Services**. No HTTP server is required for core functionality.

- `atelier ...` — full CLI for context, traces, rubrics, memory, and runtime management
- `atelier-mcp` — MCP stdio server for agent host integration
- `atelier background ...` — manages OS-level background services (controller + stack)
- `atelier stack ...` — manages the optional API + frontend processes manually

Telemetry is on by default; disable with `atelier telemetry off` or `ATELIER_TELEMETRY=0`.

## How Atelier Saves LLM Cost

Atelier reduces token spend at every layer of the agent loop — context loading, tool calls, model selection, and recovery. The savings stack:

| Mechanism                                | What it does                                                                                                                                                        | Typical savings                                                                                                                         |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **Context Reuse (ReasonBlocks)**         | Retrieves known procedures instead of letting the agent rediscover them from scratch each session.                                                                  | Avoids 1–3 rounds of exploration per repeat task.                                                                                       |
| **Context Compression**                  | Summarises long-running ledgers into compact reusable state so the context window stays small.                                                                      | Cuts session prompt size as conversations grow.                                                                                         |
| **Failure Rescue**                       | Surfaces targeted procedures the moment a known error pattern reappears — no retry-and-discover loop.                                                               | Eliminates duplicate debugging cycles.                                                                                                  |
| **Loop Detection & Watchdogs**           | Detects thrashing, second-guessing, and repeated failures, then halts or rescues before the agent burns context.                                                    | Stops runaway loops that quietly drain budget.                                                                                          |
| **Model Routing**                        | Sends each task to the right model (Haiku/Sonnet/Opus or cross-vendor) based on complexity, budget, and quality policy. Includes counterfactual pricing simulation. | Routes simple work to cheap models, hard work to capable ones.                                                                          |
| **Tool Supervision**                     | Cached reads, memoized searches, batch edits with rollback, injection-guarded grep — fewer redundant tool calls.                                                    | Removes duplicate filesystem and search work.                                                                                           |
| **Outline-mode reads**                   | `mcp__atelier__read` returns signatures/structure instead of full bodies for files over ~200 LOC.                                                                   | Large file reads are compressed substantially; see the benchmark harness and calibration store for current measured ratios by language. |
| **Source projection**                    | `read` can return truthful `summary` / `outline` / `compact` / `range` / `exact` views, and compact reads can carry mapping metadata for safe exact-span edits.    | Keeps discovery cheap while preserving a clean handoff back to untransformed source text.                                               |
| **Token-budgeted search/grep**           | `search` and `grep` pack results to fit an explicit token budget, ranking by relevance instead of dumping raw output.                                               | Bounded output — no accidental 50K-token grep results.                                                                                  |
| **SCIP-indexed code intel**              | Symbol lookup, callers, callees, impact, and routes come from a pre-built SCIP index, not repeated `grep`/`cat` passes.                                             | Up to ~100× fewer tokens for symbol-level questions vs. textual search.                                                                 |
| **Specialized sub-agents**               | Read-only `explore`/`review`/`research` are tool-scoped (no edit access); the spawning agent picks the model per task (cheap for lookups, stronger for precision work).                                | Right-sized model + least-privilege tools per delegated task.                                                                           |
| **Prefix-cache diagnostics**             | Middleware tracks cache-hit ratio across LangChain, OpenAI Agents, Anthropic, and Gemini, surfacing prompts that bust the cache.                                    | Helps keep Anthropic's 5-min prompt cache warm.                                                                                         |
| **Lesson Promotion & cost-cap bindings** | Promotes recurrent patterns into cost-capped routing policies tuned from observed behaviour.                                                                        | Continuous spend reduction as the runtime learns.                                                                                       |
| **Savings dashboard**                    | The frontend's Savings page (and `atelier background status`) reports token and dollar savings per session and cumulatively.                                        | Makes the savings measurable, per session and total.                                                                                    |

All savings are recorded into the run ledger and exposed via `atelier` CLI, MCP, and the optional UI — so cost reduction is observable, not just claimed.

## Capabilities

### Context Reuse

Retrieve known procedures (ReasonBlocks) before or during a task. Blocks are ranked by BM25 + optional vector similarity against the task description, domain, and error context.

```bash
atelier tools call context --dev --args '{
  "task": "Configure HTTPS for staging",
  "domain": "infra",
  "files": ["deploy/nginx.conf"]
}' --json
```

### Failure Rescue

Record every task outcome as a trace. When the same error pattern appears again, surface targeted rescue procedures from past failures.

```bash
atelier tools call rescue --dev --args '{
  "task": "Deploy to staging",
  "error": "certificate expired",
  "domain": "infra"
}' --json
```

### Rubric Verification

Define domain-specific safety checks (rubrics) that gate outputs before and after high-risk work — state changes, config mutations, rollbacks.

```bash
atelier tools call verify --dev --args '{
  "rubric_id": "rubric_state_change_safety",
  "checks": {
    "canonical_identifier_used": true,
    "pre_change_state_captured": true,
    "read_after_write_completed": true
  }
}' --json
```

### Model Routing

Route tasks to the right model based on complexity, cost budget, and available vendors. Includes cross-vendor routing advisor, counterfactual pricing simulation, and quality-aware policy evaluation.

```bash
atelier tools call route --args '{
  "task": "Refactor the auth middleware",
  "task_type": "refactor",
  "budget": "balanced"
}' --json
```

### Memory & Recall

- **Archival recall** — per-agent memory passages with embedding search
- **Semantic file memory** — token-aware outlines for Python, TypeScript, JavaScript, Go, Rust, Java, Ruby, C/C++, C#, Kotlin, PHP, Swift, Scala, Bash, SQL, YAML, TOML, JSON, Markdown, and generic text fallback
- **Symbol recall** — SCIP-indexed symbol search across Python, TypeScript/JavaScript, Go, Rust, Java, Ruby, C, and C++ when the matching indexer is available
- **Cross-vendor memory** — adapters for Claude, Codex CLI, and Gemini memory systems

### Language Support

Atelier uses one canonical language registry across detection, smart reads, repo-map tags, and SCIP indexing. Tree-sitter outlines and tags cover common code languages plus Bash, SQL, YAML, TOML, and JSON; small files can still fall back to generic/full reads when a dedicated outline does not clear the 25% savings guard.

SCIP provisioning is tiered: `scip-python` and `scip-typescript` install into Atelier's managed Node prefix when npm is available; Go/Ruby/Clang indexers are checksum-gated lazy bootstrap candidates; Rust and Java are detected from user-managed toolchains.

### Loop Detection & Watchdogs

Detect execution pathologies — thrashing, second-guessing, repeated failures — and suggest rescues before the agent burns context budget.

### Tool Supervision

Cached reads, memoized searches, injection-guarded grep, smart search, batch editing with rollback, shell command inspection, and symbol-level rename across the workspace.

### Source Projection Workflow

Atelier now treats compact reads as a **projection layer**, not just a minifier:

1. `read` chooses the cheapest truthful view for the task: `summary`, `outline`, `compact`, `range`, or `exact`.
2. Transformed reads carry a projection notice so the agent knows whether it saw structure-only or whitespace-transformed content.
3. Compact reads with `include_meta=true` can return `projection_mapping`, which records stable segment metadata for exact projected spans.
4. The `edit` tool accepts `kind: "projection"` descriptors for **exactly resolvable compact spans** and applies those edits back onto untransformed source text.
5. If the mapping is stale or the projected span is ambiguous, the edit fails closed and returns machine-readable `retry_with` guidance for an exact reread.
6. The service API exposes the same structured surface at `/v1/files/projection?path=...&view=compact`, so the UI can inspect `projection`, `projection_delta`, and `projection_mapping` without scraping tool output.

This keeps discovery cheap without turning transformed reads into an unsafe write surface.

Example projection inspection:

```bash
curl "http://localhost:8000/api/v1/files/projection?path=/repo/main.go&view=compact"
```

Example ambiguous edit fallback:

```json
{
  "code": "ambiguous_projected_range",
  "retry_with": {
    "tool": "read",
    "path": "/repo/main.go",
    "range": "L10-L14",
    "include_meta": true
  }
}
```

### Context Compression

Summarise long-running agent ledgers into compact reusable state, reducing context window pressure.

### Lesson Promotion

Surface recurrent patterns as actionable lessons. Supports automated PR creation, cost-cap bindings, and route-preference tuning from observed behavior.

### Background Processing

- **Session import** — parse agent host sessions from 18 supported hosts: antigravity, claude, codex, copilot, crush, cursor, cursor-agent, droid, gemini, goose, kilo-code, kiro, omp, openclaw, opencode, pi, qwen, roo-code
- **ReasonBlock consolidation** — deduplicate and merge related procedures
- **Auto-update** — periodic git pull + dependency sync, with automatic service restart
- **External analytics** — cost and efficiency reporting across periods (today, week, month)

### Governance & Audit

Policy enforcement, SSO-ready workspace management, role-based access control, proof gates, and audit export for compliance.

## Supported Agent Hosts

Atelier integrates with every major agent host through MCP. Configs live in `src/atelier/gateway/hosts/configs/`.

| Host         | Config             | Integration Type                     |
| ------------ | ------------------ | ------------------------------------ |
| Claude Code  | `claude.yaml`      | MCP + skills + agents + plugin hooks |
| Codex CLI    | `codex.yaml`       | MCP + AGENTS.md + hooks              |
| Copilot      | `copilot.yaml`     | MCP + instructions                   |
| opencode     | `opencode.yaml`    | MCP + Agent                          |
| Antigravity  | `antigravity.yaml` | MCP                                  |
| Cursor IDE   | `cursor.yaml`      | MCP                                  |
| Hermes Agent | `hermes.yaml`      | MCP                                  |

Per-host install guides:

- [Claude Code](docs/hosts/claude-code-install.md)
- [Codex CLI](docs/hosts/codex-install.md)
- [Copilot](docs/hosts/copilot-install.md)
- [opencode](docs/hosts/opencode-install.md)
- [Antigravity](docs/hosts/antigravity-install.md)
- [Cursor](docs/hosts/cursor-install.md)
- [Hermes](docs/hosts/hermes-install.md)

→ Full host overview: [docs/hosts/all-agent-clis.md](docs/hosts/all-agent-clis.md)

## Agents

Atelier ships a fixed set of seven specialised sub-agents across every supported host (Claude Code, opencode, Antigravity). They share one task loop, one ledger, and one set of MCP tools — only the toolset and model assignment differ.

| Agent          | Purpose                                                                                                                          | Registry default    | Tooling                                                                           |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------- | --------------------------------------------------------------------------------- |
| **`code`**     | Main coding agent. Edits, refactors, fixes bugs, and ships features with the Atelier task loop.                                  | `claude-opus-4.8`   | All tools (Atelier MCP preferred over native I/O)                                 |
| **`explore`**  | Read-only codebase explorer. Finds files, symbols, and patterns. Never edits.                                                    | `claude-sonnet-4.6` | `Read`, `Grep`, `Glob`, `mcp__atelier__{context,search,read,grep,node,symbols,usages,explore,memory}` |
| **`plan`**     | Read-only planner. Turns grounded context into a concrete implementation plan.                                                   | `claude-sonnet-4.6` | Read/search/code-intel tools; edits disallowed                                   |
| **`execute`**  | Focused executor. Applies an accepted plan or narrow task with the smallest verified edit set.                                   | `claude-opus-4.8`   | All tools                                                                         |
| **`research`** | External researcher. Fetches web pages, GitHub repos, and package docs. Never edits. Produces a structured memo with citations.  | `claude-sonnet-4.6` | `WebFetch`, `WebSearch`, `mcp__atelier__{context,search,read,memory}`             |
| **`review`**   | Adversarial code reviewer. Applies the verification ladder and rubric discipline. Never edits source files.                      | `claude-sonnet-4.6` | `Read`, `Grep`, `Glob`, `mcp__atelier__{context,read,search,verify,trace,memory}` |
| **`solve`**    | Benchmark solver. Produces artifacts early, iterates against checks, and keeps the workspace clean.                              | `claude-opus-4.8`   | All tools; sub-agent spawning disallowed                                          |

Agent source-of-truth definitions live under `integrations/agents/` (mode docs) and `integrations/shared/` (shared partials). Host-specific files are generated by `scripts/sync_agent_context.py` into:

- `integrations/claude/plugin/agents/` — Claude Code sub-agents (`code.md`, `explore.md`, `plan.md`, `execute.md`, `research.md`, `review.md`, `solve.md`)
- `integrations/opencode/agents/` — opencode agents (`atelier.md`, `explore.md`, `plan.md`, `execute.md`, `research.md`, `review.md`, `solve.md`)
- `integrations/antigravity/plugin/agents/` — Antigravity agents (`atelier-code.md`, `atelier-explore.md`, `atelier-plan.md`, `atelier-execute.md`, `atelier-research.md`, `atelier-review.md`, `atelier-solve.md`)

To regenerate the host files after editing a mode, run `make sync-agent-context`.

## Language Support

Atelier's code intelligence engine indexes files across all languages. Support levels vary by language:

### Code Intelligence (symbols, imports, call graph)

| Language   | Extensions            | Symbol Extraction | Import Resolution | Route Extraction | Call Edges |
| ---------- | --------------------- | ----------------- | ----------------- | ---------------- | ---------- |
| Python     | `.py`                 | AST-based         | Full              | Yes              | Yes        |
| JavaScript | `.js`, `.jsx`, `.mjs` | Regex             | Regex             | Yes              | —          |
| TypeScript | `.ts`, `.tsx`         | Regex             | Regex             | Yes              | —          |
| Go         | `.go`                 | Regex             | Regex             | —                | —          |
| Rust       | `.rs`                 | Regex             | Regex             | —                | —          |

All other languages receive a generic structural outline (column-0 declarations and signatures) for code-context operations.

### Semantic File Memory Outlining (tree-sitter AST)

| Language                            | Outline Support                                 |
| ----------------------------------- | ----------------------------------------------- |
| Python                              | AST-based (full function/class body extraction) |
| TypeScript, JavaScript              | AST-based (full)                                |
| Kotlin, Go, Rust, Java, Ruby        | Tree-sitter-based outline                       |
| C, C++, C#, PHP, Swift, Scala, Bash | Tree-sitter-based outline                       |

Files in any language can be indexed, searched with grep, and read with outline mode — the difference is only in how deeply the AST is analysed for code intelligence operations.

## Architecture

```text
Agent Host (Claude Code / Codex / Copilot / opencode / Antigravity / Cursor / Hermes)
        |
        |  MCP stdio  (or CLI / Python SDK)
        v
Atelier Runtime
|- Context Reuse        (ReasonBlock store — SQLite + FTS5, optional pgvector)
|- Failure Rescue       (trace recording → failure clustering → rescue procedures)
|- Rubric Verification  (domain-specific gate rules)
|- Run Ledger           (per-session execution state)
|- Model Routing        (cross-vendor advisor, counterfactual pricing)
|- Memory & Recall      (archival, semantic file, symbol, cross-vendor adapters)
|- Loop Detection       (watchdogs, pathology FSM)
|- Tool Supervision     (cached read, smart search, batch edit, shell inspect)
|- Context Compression  (ledger summarisation)
|- Lesson Promotion     (learning from traces, PR bot, cost-cap bindings)
|- Session Import       (parse host sessions → structured traces)
|- Governance           (policy, RBAC, proof gates, audit)
        |
        |- Background Services (servicectl controller + optional UI stack)
        |- Local SQLite (default) or PostgreSQL (optional, ATELIER_DATABASE_URL)
```

### Storage Layout

| Path                                  | Contents                                               |
| ------------------------------------- | ------------------------------------------------------ |
| `~/.atelier/atelier.db`               | SQLite store for blocks, traces, rubrics, jobs, memory |
| `<workspace>/.lessons/blocks/*.md`    | Markdown mirror of ReasonBlocks                        |
| `~/.atelier/traces/*.json`            | JSON mirror of recorded traces                         |
| `<workspace>/.lessons/rubrics/*.yaml` | YAML mirror of rubrics                                 |

## Optional UI Stack

The frontend provides a dashboard for analytics, sessions, traces, memory, savings, and system health.

```bash
# View logs for the visualization stack
atelier background logs stack

# Restart the entire environment
atelier background restart
```

Then open:

- frontend: [http://localhost:3125](http://localhost:3125)
- service API: [http://localhost:8787](http://localhost:8787)

Pages cover: Overview, Sessions, Session Detail, Analytics, Savings, Blocks, Memory, Rubrics, Failures, Optimizations, Plans, Reports, Watchdogs, External, Telemetry, Learnings, Insights, Outcomes, Runtime, System (20+ pages).

## Python SDK

Atelier ships two SDK surfaces for different integration patterns:

### Drop-in middleware (four frameworks, one ledger)

`AtelierMiddleware` wraps Atelier's watchdogs, loop detection, cost tracking, and
prefix-cache diagnostics behind a single class — no matter which agent framework
you use:

```python
from atelier.sdk import AtelierMiddleware

mw = AtelierMiddleware(agent_name="bugfixer", task="Refactor auth module")

# LangChain — drop-in callback handler
agent = create_agent(model=ChatAnthropic(...), callbacks=[mw.langchain()])

# OpenAI Agents SDK — lifecycle hooks
Runner.run_sync(agent, input="Refactor auth", hooks=mw.openai_hooks())

# Raw Anthropic API — tool specs + dispatch
# Pass tool_specs to client.messages.create(), call dispatch(response) after each call
tool_specs, dispatch = mw.anthropic_tools()

# Gemini ADK — lifecycle hooks
gemini_hooks = mw.gemini_adk()
gemini_hooks.on_tool_start("read_file")
```

All four surfaces share a single `RunLedger`, so cost, loops, prefix-cache metrics,
and watchdog events are unified across the session.

### Direct client API

```python
from atelier.sdk import AtelierClient

client = AtelierClient.local()

context = client.get_context(task="Apply config update", domain="state.change")
rescue = client.rescue_failure(task="Apply config update", error="cert expired")
```

→ Full SDK reference: [docs/sdk/python.md](docs/sdk/python.md)

## Safety

- No chain-of-thought storage — only observable fields (commands, errors, summaries)
- Redaction applied before trace persistence
- API keys and host tokens never written to the store
- Hooks remain opt-in for host integrations

## Docs by Audience

- **End users**: [installation.md](docs/installation.md), [quickstart.md](docs/quickstart.md), [troubleshooting.md](docs/troubleshooting.md)
- **Integrators**: [hosts/](docs/hosts/), [sdk/mcp.md](docs/sdk/mcp.md), [sdk/python.md](docs/sdk/python.md)
- **Contributors**: [engineering/contributing.md](docs/engineering/contributing.md)

→ Full documentation index: [docs/README.md](docs/README.md)

## Repository Layout

| Path            | Purpose                                                          |
| --------------- | ---------------------------------------------------------------- |
| `src/atelier/`  | Runtime, CLI, MCP server, core capabilities, gateway, storage    |
| `tests/`        | pytest suite                                                     |
| `docs/`         | User, integration, and engineering documentation                 |
| `integrations/` | Host adapter configs and install/verify scripts                  |
| `frontend/`     | Optional React + Vite visualization stack (20+ pages)            |
| `benchmarks/`   | MCP tool efficiency benchmarks (reads, grep, edit, search, etc.) |
| `docs-site/`    | Docusaurus documentation site config                             |
| `scripts/`      | Install, uninstall, hook scripts, and utilities                  |
| `examples/`     | SDK usage examples                                               |

## For Developers and Contributors

```bash
cd atelier
uv sync --all-extras
atelier init
make verify
```

- CLI reference: [docs/cli.md](docs/cli.md)
- MCP reference: [docs/sdk/mcp.md](docs/sdk/mcp.md)
- Contributing guide: [docs/engineering/contributing.md](docs/engineering/contributing.md)

Archived maintainer references live in `docs-archive/`.

## Star History

<a href="https://star-history.com/#atelier-runtime/atelier&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=atelier-runtime/atelier&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=atelier-runtime/atelier&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=atelier-runtime/atelier&type=Date" />
  </picture>
</a>
