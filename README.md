<div align="center">

# Atelier

### The Open-Source Context Runtime for Coding Agents

**One MCP server + SDK middleware — a pre-built code index, reusable procedures, failure rescue, loop detection, and cost tracking for Claude Code, Codex, Copilot, Cursor, opencode, Hermes, LangChain, the OpenAI SDK, Gemini ADK, and any MCP host.**

<!-- BENCH_HERO -->**On [CodeGraph](https://github.com/colbymchenry/codegraph)'s 7-repo benchmark vs. stock Claude Code: ~25% cheaper · 75% fewer tokens · 75% fewer tool calls (median of 4 runs/arm). [Full results ↓](#why-atelier--benchmark-results)**<!-- /BENCH_HERO -->

<p align="center">
  <a href="https://github.com/atelier-ws/atelier/blob/main/LICENSE"><img src="https://img.shields.io/github/license/atelier-ws/atelier?style=for-the-badge" alt="License" /></a>
  <a href="https://github.com/atelier-ws/atelier/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/atelier-ws/atelier/tests.yml?style=for-the-badge&label=tests" alt="Tests" /></a>
  <a href="https://github.com/atelier-ws/atelier/releases"><img src="https://img.shields.io/github/v/release/atelier-ws/atelier?style=for-the-badge" alt="Latest release" /></a>
  <a href="https://github.com/atelier-ws/atelier/releases"><img src="https://img.shields.io/github/downloads/atelier-ws/atelier/total?style=for-the-badge" alt="Total downloads" /></a>
</p>

</div>

Atelier ships the same context runtime everywhere: CLI, MCP (for all major agent hosts), and background services. It captures what your best engineers know as reusable procedures (Playbooks), learns from recurring failures, validates outputs against domain-specific rubrics, and plugs into any agent host through MCP.

## Install in One Command

```bash
curl -fsSL https://github.com/atelier-ws/atelier/releases/latest/download/install.sh | bash
```

The installer:

- installs `atelier` (single binary with CLI + MCP commands) as a user-level command in `~/.local/bin`
- initializes the runtime store under `~/.atelier`
- starts the detached `servicectl` background loop (systemd on Linux, launchd on macOS)
- optionally starts the visualization stack when npm is available
- installs supported host integrations when the host CLI is found on `PATH`

Check the installed runtime:

```bash
atelier --version
atelier mcp --version
atelier background status
```

## What Runs After Install

The installed product gives you **CLI + MCP + Background Services**. No HTTP server is required for core functionality.

- `atelier ...` — full CLI for context, traces, rubrics, memory, and runtime management
- `atelier mcp` — MCP stdio server for agent host integration (via `atelier mcp --host <host>`)
- `atelier background ...` — manages OS-level background services (controller + stack)
- `atelier stack ...` — manages the optional API + frontend processes manually

Telemetry is on by default; disable with `atelier telemetry off` or `ATELIER_TELEMETRY=0`.

## Why Atelier? — Benchmark Results

When a coding agent explores an unfamiliar codebase, it burns tokens and tool calls on `grep` / `glob` / `read` discovery sweeps — and the larger the repo, the worse it gets. Atelier gives the agent a pre-built [SCIP](https://github.com/sourcegraph/scip) code index, supervised (cached, token-budgeted, injection-guarded) tools, and a disciplined task loop, so it queries structure instead of re-scanning files.

To measure the effect, we ran the A/B from [CodeGraph](https://github.com/colbymchenry/codegraph)'s benchmark — the **same 7 real-world repositories** and the **same architecture questions** — against Atelier:

- **WITH Atelier** — Claude Code running the `atelier:code` agent: Atelier's MCP server (code intelligence + supervised tools) plus a pre-built index of the repo.
- **WITHOUT (baseline)** — stock Claude Code with no plugins, hooks, or MCP servers; only the built-in `Read` / `Grep` / `Bash` tools.

Both arms use the **same model** (Claude Sonnet, headless `claude -p`), the **same question** per repo, and the same isolated config — the only variable is Atelier. **4 runs per arm, median reported.**

<!-- BENCH_AVG -->
**Pooled across all 7 repos (median of 4 runs/arm, Claude Sonnet): ~25% cheaper · 75% fewer tokens · 75% fewer tool calls — but ~112% slower.** Atelier is cheaper on 5 of 7 repos: the stock baseline answers by spawning an Explore subagent that fans out into 14–40 `grep`/`read` calls, while Atelier resolves each question in 0–12 targeted calls. The consistent regression is **time** — Atelier builds a code index on large repos (VS Code: ~1034s on ~10k files), and that wall-clock cost isn't recovered by a single question.

- **Tokens & tool calls:** cut 60–98% on 5 of 7 repos (Django −92% tokens / −100% calls, Tokio −98% / −100%, OkHttp −77% / −100%).
- **Cost:** −25% pooled, bimodal — much cheaper on Django/Tokio/OkHttp, slightly pricier on Excalidraw and Alamofire where Atelier's index-write + output cost outweighs the baseline's cheap cached discovery.
<!-- /BENCH_AVG -->

<!-- BENCH_TABLE_START -->
| Codebase | Cost | Tokens | Time | Tool calls |
| --- | --- | --- | --- | --- |
| VS Code | 13.1% cheaper | 77.5% fewer | 837.3% slower | 67.9% fewer |
| Excalidraw | 20.5% pricier | 75.5% fewer | 20.2% faster | 70% fewer |
| Django | 84.8% cheaper | 92% fewer | 56.7% faster | 100% fewer |
| Tokio | 89.1% cheaper | 97.5% fewer | 69.2% faster | 100% fewer |
| OkHttp | 81% cheaper | 76.8% fewer | 22.4% faster | 100% fewer |
| gin | 5.5% cheaper | 5.2% more | 67.7% slower | even |
| Alamofire | 27.4% pricier | 63% fewer | even | 61.2% fewer |
| **Overall (pooled)** | 24.7% cheaper | 74.9% fewer | 111.5% slower | 74.9% fewer |

<sub>Positive = Atelier better. Measured 2026-06-16 on Claude Sonnet (`claude-sonnet-4-6`), 4 runs per arm (56 runs total), each repo pinned at a fixed commit. **Tokens and tool calls are counted from the full wire capture (main agent + every subagent).** The stock baseline delegates discovery to an Explore subagent whose usage the `claude -p` receipt omits, so receipt-only counts undercount the baseline 10–40×; cost and time come from the receipt, which already bills subagent spend. Raw results: [`benchmarks/codebench/results/published/`](benchmarks/codebench/results/published/). Regenerate with `uv run --project benchmarks python benchmarks/codebench/cg_report_wire.py benchmarks/codebench/results/published`.</sub>
<!-- BENCH_TABLE_END -->

<details>
<summary><b>Methodology &amp; the 7 repositories</b></summary>

Each arm is `claude -p` (Claude Sonnet) run headlessly against the repo in a contamination-free config — real subscription auth, but no globally-installed plugins/hooks/MCP, so the only A/B difference is Atelier itself. The Atelier arm additionally loads the generated Claude plugin (`--agent atelier:code`) and pre-builds its code index (`atelier code index`) before the timed run, mirroring CodeGraph's pre-indexed setup. Repositories are cloned at a pinned commit and indexed by the same Atelier build that serves them.

| Repo | Language | Question |
| --- | --- | --- |
| VS Code | TypeScript | How does the extension host communicate with the main process? |
| Excalidraw | TypeScript | How does Excalidraw render and update canvas elements? |
| Django | Python | How does Django's ORM build and execute a query from a QuerySet? |
| Tokio | Rust | How does tokio schedule and run async tasks on its runtime? |
| OkHttp | Java | How does OkHttp process a request through its interceptor chain? |
| gin | Go | How does gin route requests through its middleware chain? |
| Alamofire | Swift | How does Alamofire build, send, and validate a request? |

**Metrics.** _Cost_ and _time_ come from the run's `total_cost_usd` and wall-clock — the receipt already bills any subagent the agent spawns. _Tokens_ (input + cache-read + cache-creation + output) and _tool calls_ are summed from the captured wire traffic across the main agent **and every subagent**, because the CLI receipt's `usage`/`num_turns` fields report only the main agent — which undercounts a baseline that delegates discovery to an Explore subagent (often 10–40×). Each cell is the saving at the **median of 4 runs per arm**; timed-out or errored runs are dropped before the median.

**Honest caveats.** This measures Atelier-enabled Claude Code vs. stock Claude Code — _not_ Atelier vs. CodeGraph. Numbers vary run-to-run, and the questions are about famous OSS libraries the model partly knows, so the benchmark scores **efficiency, not answer accuracy** (same as CodeGraph's). The real Atelier regression is **wall-clock time**: building a code index on a large repo (VS Code, ~10k files) costs ~12 min a single question never recovers; on small/medium repos Atelier is faster. On tiny gin (191 files) Atelier's fixed overhead isn't amortized.

</details>

<details>
<summary><b>Per-repo absolute numbers (WITH / WITHOUT)</b></summary>

<!-- BENCH_RAW_START -->
| Codebase | arm | cost_usd | tokens | time_s | tool_calls | reps |
| --- | --- | --- | --- | --- | --- | --- |
| VS Code | baseline | 0.2887 | 1,008,178 | 110.3 | 28 | 4 |
| VS Code | atelier | 0.2509 | 226,994 | 1033.8 | 9 | 4 |
| Excalidraw | baseline | 0.3283 | 1,345,003 | 161.4 | 40 | 4 |
| Excalidraw | atelier | 0.3956 | 330,015 | 128.8 | 12 | 4 |
| Django | baseline | 0.2076 | 291,064 | 77.6 | 14 | 4 |
| Django | atelier | 0.0316 | 23,342 | 33.6 | 0 | 4 |
| Tokio | baseline | 0.3115 | 955,610 | 125.4 | 30 | 4 |
| Tokio | atelier | 0.0338 | 23,540 | 38.6 | 0 | 4 |
| OkHttp | baseline | 0.1418 | 99,786 | 34.7 | 5 | 4 |
| OkHttp | atelier | 0.0269 | 23,104 | 26.9 | 0 | 4 |
| gin | baseline | 0.2312 | 211,272 | 42.0 | 7 | 4 |
| gin | atelier | 0.2184 | 222,298 | 70.5 | 7 | 4 |
| Alamofire | baseline | 0.3438 | 1,097,266 | 145.3 | 24 | 4 |
| Alamofire | atelier | 0.4381 | 405,526 | 141.3 | 10 | 4 |

<sub>Per-arm medians over 4 runs. `cost_usd` and `time_s` from the receipt; `tokens` (input + cache-read + cache-creation + output) and `tool_calls` from the wire capture (main + subagents). Note the baseline's true token counts — e.g. Excalidraw's 1.35M — vs the ~50k the receipt's main-agent `usage` field alone reports. Full run data: [`benchmarks/codebench/results/published/`](benchmarks/codebench/results/published/).</sub>
<!-- BENCH_RAW_END -->

</details>

### Reproduce it

The 7 repositories are wired up as efficiency-only CodeBench tasks (`cg_*`). Run the full A/B and regenerate the table:

```bash
# Run all 7 repos, 4 reps per arm (56 runs total)
uv run atelier benchmark codebench \
  --task cg_gin --task cg_alamofire --task cg_excalidraw --task cg_tokio \
  --task cg_okhttp --task cg_django --task cg_vscode \
  --task-source-dir .bench-tasks \
  --reps 4 --model sonnet

# Regenerate the wire-corrected table from a run directory
uv run --project benchmarks python benchmarks/codebench/cg_report_wire.py \
  benchmarks/codebench/results/published
```

Published canonical results (all tasks, flat) live in [`benchmarks/codebench/results/published/`](benchmarks/codebench/results/published/). Timestamped run dirs (local scratch) are gitignored.

## How Atelier Saves LLM Cost

Atelier reduces token spend at every layer of the agent loop — context loading, tool calls, model selection, and recovery. The savings stack:

| Mechanism                                | What it does                                                                                                                                                            | Typical savings                                                                                                                         |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **Context Reuse (Playbooks)**         | Retrieves known procedures instead of letting the agent rediscover them from scratch each session.                                                                      | Avoids 1–3 rounds of exploration per repeat task.                                                                                       |
| **Context Compression**                  | Summarises long-running ledgers into compact reusable state so the context window stays small.                                                                          | Cuts session prompt size as conversations grow.                                                                                         |
| **Failure Rescue**                       | Surfaces targeted procedures the moment a known error pattern reappears — no retry-and-discover loop.                                                                   | Eliminates duplicate debugging cycles.                                                                                                  |
| **Loop Detection & Watchdogs**           | Detects thrashing, second-guessing, and repeated failures, then halts or rescues before the agent burns context.                                                        | Stops runaway loops that quietly drain budget.                                                                                          |
| **Model Routing**                        | Sends each task to the right model (Haiku/Sonnet/Opus or cross-vendor) based on complexity, budget, and quality policy. Includes counterfactual pricing simulation.     | Routes simple work to cheap models, hard work to capable ones.                                                                          |
| **Tool Supervision**                     | Cached reads, memoized searches, batch edits with rollback, injection-guarded grep — fewer redundant tool calls.                                                        | Removes duplicate filesystem and search work.                                                                                           |
| **Outline-mode reads**                   | `mcp__atelier__read` returns signatures/structure instead of full bodies for files over ~200 LOC.                                                                       | Large file reads are compressed substantially; see the benchmark harness and calibration store for current measured ratios by language. |
| **Source projection**                    | `read` can return truthful `summary` / `outline` / `compact` / `range` / `exact` views, and compact reads can carry mapping metadata for safe exact-span edits.         | Keeps discovery cheap while preserving a clean handoff back to untransformed source text.                                               |
| **Token-budgeted search/grep**           | `search` and `grep` pack results to fit an explicit token budget, ranking by relevance instead of dumping raw output.                                                   | Bounded output — no accidental 50K-token grep results.                                                                                  |
| **SCIP-indexed code intel**              | Symbol lookup, callers, callees, and routes come from a pre-built SCIP index, not repeated `grep`/`cat` passes.                                                 | 10–100× fewer tokens on symbol questions in large repos vs. grep-and-read; workload-dependent, measured per call.                                                                 |
| **Specialized sub-agents**               | Read-only `explore`/`review`/`research` are tool-scoped (no edit access); the spawning agent picks the model per task (cheap for lookups, stronger for precision work). | Right-sized model + least-privilege tools per delegated task.                                                                           |
| **Prefix-cache diagnostics**             | Middleware tracks cache-hit ratio across LangChain, OpenAI Agents, Anthropic, and Gemini, surfacing prompts that bust the cache.                                        | Surfaces prompts that bust the host's prompt cache — caching itself is the host's job, not Atelier's.                                                                                         |
| **Lesson Promotion & cost-cap bindings** | Promotes recurrent patterns into cost-capped routing policies tuned from observed behaviour.                                                                            | Continuous spend reduction as the runtime learns.                                                                                       |
| **Savings dashboard**                    | The frontend's Savings page (and `atelier background status`) reports token and dollar savings per session and cumulatively.                                            | Makes the savings measurable, per session and total.                                                                                    |

All savings are recorded into the run ledger and inspectable per session via `atelier` CLI, MCP, and the optional UI — measured token usage alongside clearly-labelled counterfactual estimates, not unverified marketing numbers. Counterfactual value is priced at the model's real input rate; models with no known price read as $0 rather than an inflated guess.

## Capabilities

### Context Reuse

Retrieve known procedures (Playbooks) before or during a task. Blocks are ranked by BM25 + optional vector similarity against the task description, domain, and error context.

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
- **Playbook consolidation** — deduplicate and merge related procedures
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

| Agent          | Purpose                                                                                                                         | Registry default    | Tooling                                                                                               |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------------------------- |
| **`code`**     | Main coding agent. Edits, refactors, fixes bugs, and ships features with the Atelier task loop.                                 | `claude-opus-4.8`   | All tools (Atelier MCP preferred over native I/O)                                                     |
| **`explore`**  | Read-only codebase explorer. Finds files, symbols, and patterns. Never edits.                                                   | `claude-sonnet-4.6` | `Read`, `Grep`, `Glob`, `mcp__atelier__{context,search,read,grep,node,symbols,usages,explore,memory}` |
| **`plan`**     | Read-only planner. Turns grounded context into a concrete implementation plan.                                                  | `claude-sonnet-4.6` | Read/search/code-intel tools; edits disallowed                                                        |
| **`execute`**  | Focused executor. Applies an accepted plan or narrow task with the smallest verified edit set.                                  | `claude-opus-4.8`   | All tools                                                                                             |
| **`research`** | External researcher. Fetches web pages, GitHub repos, and package docs. Never edits. Produces a structured memo with citations. | `claude-sonnet-4.6` | `WebFetch`, `WebSearch`, `mcp__atelier__{context,search,read,memory}`                                 |
| **`review`**   | Adversarial code reviewer. Applies the verification ladder and rubric discipline. Never edits source files.                     | `claude-sonnet-4.6` | `Read`, `Grep`, `Glob`, `mcp__atelier__{context,read,search,verify,trace,memory}`                     |
| **`solve`**    | Autonomous task solver. Produces the required result early, iterates against real checks, and owns completion.                  | `claude-opus-4.8`   | All tools; sub-agent spawning disallowed                                                              |

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
|- Context Reuse        (Playbook store — SQLite + FTS5, optional pgvector)
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
| `<workspace>/.lessons/blocks/*.md`    | Markdown mirror of Playbooks                        |
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

- **End users**: [installation.md](docs/installation.md), [troubleshooting.md](docs/troubleshooting.md)
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

## License

Atelier is licensed under the [Apache License 2.0](LICENSE).

## Star History

<a href="https://star-history.com/#atelier-ws/atelier&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=atelier-ws/atelier&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=atelier-ws/atelier&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=atelier-ws/atelier&type=Date" />
  </picture>
</a>
