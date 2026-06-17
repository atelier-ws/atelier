# Atelier

<p align="center">
  <a href="https://github.com/atelier-ws/atelier/blob/main/LICENSE"><img src="https://img.shields.io/github/license/atelier-ws/atelier?style=for-the-badge" alt="License" /></a>
  <a href="https://github.com/atelier-ws/atelier/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/atelier-ws/atelier/tests.yml?style=for-the-badge&label=tests" alt="Tests" /></a>
  <a href="https://github.com/atelier-ws/atelier/releases"><img src="https://img.shields.io/github/v/release/atelier-ws/atelier?style=for-the-badge" alt="Latest release" /></a>
  <a href="https://github.com/atelier-ws/atelier/releases"><img src="https://img.shields.io/github/downloads/atelier-ws/atelier/total?style=for-the-badge" alt="Total downloads" /></a>
</p>

Local MCP tools that make coding agents more grounded and less repetitive.

Atelier plugs into Claude Code, Codex, Copilot, Cursor, opencode, Antigravity, and Hermes. It gives agents structured code search, safe file reads/edits, memory, session recall, and cost-aware runtime tools so they spend fewer turns rediscovering your repository.

Current published CodeBench run: **24.7% cheaper** and **74.9% fewer tokens/tool calls** overall, with slower wall-clock on the pooled benchmark because large-repo indexing is counted up front. See [Results](#results).

## Get Started

### 1. Install Atelier

```bash
curl -fsSL https://github.com/atelier-ws/atelier/releases/latest/download/install.sh | bash
```

Open a new terminal if your shell does not immediately find `atelier`.

```bash
atelier --help
```

Already installed?

```bash
atelier update
```

### 2. Initialize a Project

Run this once per repository:

```bash
cd your-project
atelier init
```

`atelier init` creates the local runtime store and, by default, bootstraps the code index for the current git repo. Use `atelier init --no-index` if you want to skip indexing.

### 3. Connect Your Agent

The release installer attempts to install supported host integrations when it detects the host CLI or workspace files. If you need to wire an MCP host manually, configure it to run:

```bash
atelier mcp --host claude
```

Replace `claude` with the host you use:

| Host        | MCP command                      |
| ----------- | -------------------------------- |
| Claude Code | `atelier mcp --host claude`      |
| Codex CLI   | `atelier mcp --host codex`       |
| Copilot     | `atelier mcp --host copilot`     |
| opencode    | `atelier mcp --host opencode`    |
| Antigravity | `atelier mcp --host antigravity` |
| Cursor      | `atelier mcp --host cursor`      |
| Hermes      | `atelier mcp --host hermes`      |

Host-specific guides live in [docs/hosts/](docs/hosts/).

### 4. Use Your Agent Normally

Once connected, your agent can call Atelier tools instead of repeatedly scanning files with raw grep/read loops. The most important tools are:

| Tool                             | What it gives the agent                             |
| -------------------------------- | --------------------------------------------------- |
| `search` / `grep`                | Token-budgeted search across code and docs.         |
| `read`                           | Budgeted file reads with outline/range/full modes.  |
| `node`                           | The exact source for one symbol.                    |
| `callers` / `callees` / `usages` | Indexed code relationships.                         |
| `edit`                           | Deterministic file edits with validation hooks.     |
| `memory`                         | Local memory and recall operations.                 |
| `shell`                          | Compact command execution when no direct tool fits. |

Check what your installed build exposes:

```bash
atelier tools list
```

## Why Atelier?

Coding agents burn context when they have to rediscover a codebase from scratch. They often start by listing files, grepping broad patterns, opening large files, and repeating similar searches after every turn.

Atelier gives them a local runtime with:

- code intelligence for symbols, callers, callees, usages, and structural search
- supervised file reads and edits with bounded output
- local memory and session recall
- session import from supported agent hosts
- cost and savings reporting
- optional service and dashboard for inspecting activity

The goal is not to replace your agent. Atelier gives the agent better tools so it can answer with less blind exploration.

## Results

Published benchmark artifacts live in [benchmarks/codebench/results/published/](benchmarks/codebench/results/published/). Treat those files as the source of truth for benchmark numbers.

The current published CodeGraph-style run covers 7 repositories, 4 reps per arm, with 28/28 valid runs in both arms.

| Codebase            | Cost              | Tokens          | Time              | Tool calls      |
| ------------------- | ----------------- | --------------- | ----------------- | --------------- |
| VS Code             | 13.1% cheaper     | 77.5% fewer     | 837.3% slower     | 67.9% fewer     |
| Excalidraw          | 20.5% pricier     | 75.5% fewer     | 20.2% faster      | 70% fewer       |
| Django              | 84.8% cheaper     | 92% fewer       | 56.7% faster      | 100% fewer      |
| Tokio               | 89.1% cheaper     | 97.5% fewer     | 69.2% faster      | 100% fewer      |
| OkHttp              | 81% cheaper       | 76.8% fewer     | 22.4% faster      | 100% fewer      |
| gin                 | 5.5% cheaper      | 5.2% more       | 67.7% slower      | even            |
| Alamofire           | 27.4% pricier     | 63% fewer       | even              | 61.2% fewer     |
| **Overall, pooled** | **24.7% cheaper** | **74.9% fewer** | **111.5% slower** | **74.9% fewer** |

Caveat: the pooled wall-clock result is slower because large-repo index startup is included. Atelier is strongest when discovery cost dominates or when the index is reused across multiple questions.

Regenerate the published table from the checked-in artifacts:

```bash
uv run --project benchmarks python -m benchmarks.codebench.cg_report_wire \
  benchmarks/codebench/results/published
```

## How Atelier stands against others on read tasks

`atelier benchmark providers` - doesn't run any llm, all local indexing benchmarks

| Test type         | [atelier](https://github.com/atelier-ws/atelier) | [atelier-zoekt](https://github.com/sourcegraph/zoekt) | [ast-grep](https://github.com/ast-grep/ast-grep) | [code-index-mcp](https://github.com/johnhuang316/code-index-mcp) | [codegraph](https://github.com/colbymchenry/codegraph) | [jcodemunch-mcp](https://github.com/jgravelle/jcodemunch-mcp) | [scip-python](https://github.com/sourcegraph/scip-python) | [serena](https://github.com/oraios/serena) | [universal-ctags](https://github.com/universal-ctags/ctags) | [zoekt](https://github.com/sourcegraph/zoekt) |
| ----------------- | ------------------------------------------------ | ----------------------------------------------------- | ------------------------------------------------ | ---------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------ | ----------------------------------------------------------- | --------------------------------------------- |
| callees           | **1.00 / 114 / 78**                              | -                                                     | -                                                | -                                                                | 0.85 / 135 / 112                                       | 0.97 / 283 / 1654                                             | -                                                         | -                                          | -                                                           | -                                             |
| callers           | **1.00 / 48 / 72** \*                            | -                                                     | 0.52 / 342 / 276                                 | -                                                                | 0.99 / 136 / 204                                       | 0.53 / 201 / 1666                                             | 0.13 / 0.09 / 59                                          | 0.86 / 214 / 450                           | -                                                           | -                                             |
| exact_search      | **1.00 / 53 / 26**                               | 0.98 / 7 / 73                                         | -                                                | 0.98 / 325 / 247                                                 | 1.00 / 132 / 436                                       | 1.00 / 50 / 162                                               | -                                                         | 1.00 / 223 / 88                            | -                                                           | 1.00 / 6 / 101                                |
| exact_symbol      | **1.00 / 11 / 26**                               | -                                                     | -                                                | -                                                                | 1.00 / 137 / 436                                       | 1.00 / 10 / 431                                               | 1.00 / 0.09 / 51                                          | 1.00 / 304 / 54                            | 1.00 / 1 / 66                                               | -                                             |
| file_outline      | **1.00 / 33 / 126** \*                           | -                                                     | -                                                | 0.99 / 321 / 975                                                 | -                                                      | 1.00 / 5 / 795                                                | 1.00 / 0.09 / 183                                         | 0.85 / 101 / 51                            | 1.00 / 6 / 687                                              | -                                             |
| fuzzy_symbol      | 0.99 / 90 / 27                                   | -                                                     | -                                                | -                                                                | -                                                      | **1.00 / 398 / 434**                                          | -                                                         | -                                          | -                                                           | -                                             |
| nohit_search      | 1.00 / 81 / 3 \*                                 | 1.00 / 7 / 30                                         | -                                                | 1.00 / 308 / 47                                                  | **1.00 / 146 / 1**                                     | 1.00 / 55 / 61                                                | -                                                         | 1.00 / 229 / 1                             | -                                                           | 1.00 / 6 / 29                                 |
| references        | **1.00 / 22 / 43**                               | -                                                     | -                                                | -                                                                | -                                                      | 0.28 / 7 / 152                                                | 0.06 / 0.09 / 52                                          | 0.87 / 193 / 651                           | -                                                           | -                                             |
| structural_search | **0.89 / 26 / 31**                               | -                                                     | 0.15 / 348 / 633                                 | -                                                                | -                                                      | -                                                             | -                                                         | -                                          | -                                                           | -                                             |
| substring_search  | **1.00 / 76 / 131**                              | 0.99 / 9 / 292                                        | -                                                | 0.78 / 319 / 862                                                 | 1.00 / 133 / 1012                                      | 0.81 / 46 / 537                                               | -                                                         | 0.94 / 227 / 638                           | -                                                           | 1.00 / 8 / 587                                |

Starred rows:

- `callers`: `scip-python` is much smaller and faster because it returns a bare file list, while Atelier includes caller names and line numbers; Atelier is still more correct in this run.
- `file_outline`: `serena` uses a much smaller top-level class list, while Atelier includes line ranges, method-level entries, and import roots.
- `nohit_search`: `codegraph` and `serena` return a 1-token no-hit result; Atelier returns a 3-token explicit no-hit result.

## Privacy and Data

Atelier's runtime store and code index are local by default. Core MCP operation does not require the HTTP service or a hosted Atelier backend.

Some optional features can involve external systems, depending on how you configure them:

- agent model calls still go through the agent/provider you already use
- `web_fetch` fetches public HTTP/HTTPS pages when an agent calls it
- telemetry controls are available through `atelier telemetry`
- optional provider, routing, memory, or dashboard integrations may require their own credentials

Inspect current telemetry state:

```bash
atelier telemetry status
```

## Supported Hosts

Atelier ships host config and integration assets for:

| Host        | Config source                                        |
| ----------- | ---------------------------------------------------- |
| Claude Code | `src/atelier/gateway/hosts/configs/claude.yaml`      |
| Codex CLI   | `src/atelier/gateway/hosts/configs/codex.yaml`       |
| Copilot     | `src/atelier/gateway/hosts/configs/copilot.yaml`     |
| opencode    | `src/atelier/gateway/hosts/configs/opencode.yaml`    |
| Antigravity | `src/atelier/gateway/hosts/configs/antigravity.yaml` |
| Cursor      | `src/atelier/gateway/hosts/configs/cursor.yaml`      |
| Hermes      | `src/atelier/gateway/hosts/configs/hermes.yaml`      |

Session import support is currently narrower than host config support:

```text
antigravity, claude, codex, copilot, cursor, opencode
```

## Optional Dashboard

The core MCP server works without the dashboard. If you want the local service and frontend:

```bash
atelier service start
```

The optional stack tooling uses these default ports:

| Component   | Default URL           |
| ----------- | --------------------- |
| Service API | `http://0.0.0.0:8787` |
| Frontend    | `http://0.0.0.0:3125` |

## Uninstall

Remove host integrations and Atelier-managed install state:

```bash
atelier uninstall
```

Preview first:

```bash
atelier uninstall --dry-run
```

Remove runtime state and known host residue as well:

```bash
atelier uninstall --purge
```

## Developer Notes

The implementation sources of truth are:

| Area                                 | Source                                                  |
| ------------------------------------ | ------------------------------------------------------- |
| Package metadata and console scripts | `pyproject.toml`                                        |
| CLI registration                     | `src/atelier/gateway/cli/`                              |
| MCP tools                            | `src/atelier/gateway/adapters/mcp_server.py`            |
| Host configs                         | `src/atelier/gateway/hosts/configs/`                    |
| Session import registry              | `src/atelier/gateway/hosts/session_parsers/registry.py` |
| Language registry                    | `src/atelier/infra/code_intel/languages.py`             |
| Host integration assets              | `integrations/`                                         |
| Installer/build scripts              | `scripts/`                                              |

Useful development commands:

```bash
uv sync --all-extras
uv run atelier --help
make test-fast
make docs-check
```

For broader code changes, use the Makefile surface: `make lint`, `make typecheck`, `make test-fast`, or `make verify` depending on scope.

## Documentation

| Topic                | File                                                         |
| -------------------- | ------------------------------------------------------------ |
| Installation         | [docs/installation.md](docs/installation.md)                 |
| CLI                  | [docs/cli.md](docs/cli.md)                                   |
| MCP SDK              | [docs/sdk/mcp.md](docs/sdk/mcp.md)                           |
| Python SDK           | [docs/sdk/python.md](docs/sdk/python.md)                     |
| Host overview        | [docs/hosts/all-agent-clis.md](docs/hosts/all-agent-clis.md) |
| Troubleshooting      | [docs/troubleshooting.md](docs/troubleshooting.md)           |
| Production readiness | [docs/production-readiness.md](docs/production-readiness.md) |

## License

Atelier is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
