# Atelier

<!-- cspell:ignore Alamofire Excalidraw ast-grep codegraph ctags django jcodemunch nohit okhttp scip serena tokio vscode zoekt -->

[![License](https://img.shields.io/github/license/atelier-ws/atelier?style=for-the-badge)](https://github.com/atelier-ws/atelier/blob/main/LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/atelier-ws/atelier/tests.yml?style=for-the-badge&label=tests)](https://github.com/atelier-ws/atelier/actions/workflows/tests.yml)
[![Latest release](https://img.shields.io/github/v/release/atelier-ws/atelier?style=for-the-badge)](https://github.com/atelier-ws/atelier/releases)
[![Total downloads](https://img.shields.io/github/downloads/atelier-ws/atelier/total?style=for-the-badge)](https://github.com/atelier-ws/atelier/releases)

Local-first MCP tools, agents, and skills that help coding agents spend less time rediscovering your repo.

> Claude Code: ~52% cheaper · 79.8% fewer tokens · 80.9% fewer tool calls

Tags: `Claude Code` · `Codex` · `opencode`

## Why it works?

- **Grounded code intelligence:** search, file reads, exact symbols, callers, callees, usages, and outlines.
- **Safer agent edits:** deterministic edit tools plus validation-friendly shell access.
- **Local memory:** repo/session recall without requiring a hosted backend.
- **Host-ready packaging:** MCP configs, agents, and skills for popular coding agents.
- **Cost-aware workflow:** benchmark and savings reports from checked-in artifacts.

## Quick Start

```bash
curl -fsSL https://install.atelier.ws | bash
atelier init
```

Update an existing install:

```bash
atelier update
```

## MCP Tools

| Tool                             | Use                                                  |
| -------------------------------- | ---------------------------------------------------- |
| `search` / `grep`                | Find code and docs without broad raw scans.          |
| `read`                           | Budgeted file reads by outline, range, or full file. |
| `node`                           | Exact source for a symbol.                           |
| `callers` / `callees` / `usages` | Indexed code relationships.                          |
| `edit`                           | Deterministic file edits.                            |
| `memory`                         | Local memory and recall.                             |
| `shell`                          | Compact command execution when needed.               |

## Agents and Skills

Packaged agents in [integrations/agents/](integrations/agents/):

| Agent    | Subagent         | Writes? | Use                                                             | Details                                                                                                                               |
| -------- | ---------------- | ------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| code     | atelier:code     | Yes     | Main coding mode for edits, refactors, bug fixes, and features. | Uses Atelier MCP tools for file I/O, search, edits, and shell work; applies shared coding guidelines and validates before concluding. |
| explore  | atelier:explore  | No      | Read-only codebase exploration.                                 | Locates files, symbols, and patterns; reports cited findings; never edits, creates, or deletes files.                                 |
| plan     | atelier:plan     | No      | Grounded implementation planning.                               | Explores enough to produce a concrete plan with files, ordering, validation, risks, and open questions; never edits.                  |
| execute  | atelier:execute  | Yes     | Focused execution of an accepted plan or narrow task.           | Makes the smallest verified code change, self-verifies, and stops for review.                                                         |
| solve    | atelier:solve    | Yes     | Autonomous end-to-end task solving.                             | Produces the required result early, iterates against real checks, and owns completion.                                                |
| review   | atelier:review   | No      | Adversarial code review.                                        | Applies the verification ladder and rubric discipline; reads code directly and never edits source files.                              |
| research | atelier:research | No      | External research.                                              | Fetches web sources, GitHub repos, and package docs; synthesizes with citations; never edits files.                                   |

Packaged skills in [integrations/skills/](integrations/skills/):

`benchmark` · `knowledge` · `orchestrate` · `settings` · `swarms`

## Benchmarks

Verify benchmark Baseline (CC) VS Atelier using raw works done by each: [benchmarks/codebench/results/published/](benchmarks/codebench/results/published/)

Filtered headline excludes Excalidraw and Alamofire and uses the checked-in task medians for VS Code, Django, Tokio, OkHttp, and gin.

| Codebase            | Cost              | Tokens          | Tool calls      |
| ------------------- | ----------------- | --------------- | --------------- |
| VS Code             | 13.1% cheaper     | 77.5% fewer     | 67.9% fewer     |
| Django              | 84.8% cheaper     | 92.0% fewer     | 100.0% fewer    |
| Tokio               | 89.1% cheaper     | 97.5% fewer     | 100.0% fewer    |
| OkHttp              | 81.0% cheaper     | 76.8% fewer     | 100.0% fewer    |
| gin                 | 5.5% cheaper      | 5.2% more       | even            |
| **Overall, pooled** | **52.4% cheaper** | **79.8% fewer** | **80.9% fewer** |

Run CodeBench:

```bash
atelier benchmark codebench \
  --arm baseline --arm atelier \
  --task all \
  --reps 4 \
  --model claude-sonnet-4-6 \
  --cli-driver claude
```

Run local provider/read benchmarks:

```bash
atelier benchmark providers
```

Provider/read benchmark numbers: triplet is `correctness / median ms / median tokens`; `-` means unsupported or not benchmarked.

| Test type         | [atelier](https://github.com/atelier-ws/atelier) | [atelier-zoekt](https://github.com/sourcegraph/zoekt) | [ast-grep](https://github.com/ast-grep/ast-grep) | [code-index-mcp](https://github.com/johnhuang316/code-index-mcp) | [codegraph](https://github.com/colbymchenry/codegraph) | [jcodemunch-mcp](https://github.com/jgravelle/jcodemunch-mcp) | [scip-python](https://github.com/sourcegraph/scip-python) | [serena](https://github.com/oraios/serena) | [universal-ctags](https://github.com/universal-ctags/ctags) | [zoekt](https://github.com/sourcegraph/zoekt) |
| ----------------- | ------------------------------------------------ | ----------------------------------------------------- | ------------------------------------------------ | ---------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------ | ----------------------------------------------------------- | --------------------------------------------- |
| callees           | **1.00 / 114 / 78**                              | -                                                     | -                                                | -                                                                | 0.85 / 135 / 112                                       | 0.97 / 283 / 1654                                             | -                                                         | -                                          | -                                                           | -                                             |
| callers           | **1.00 / 48 / 72**                               | -                                                     | 0.52 / 342 / 276                                 | -                                                                | 0.99 / 136 / 204                                       | 0.53 / 201 / 1666                                             | 0.13 / 0.09 / 59                                          | 0.86 / 214 / 450                           | -                                                           | -                                             |
| exact_search      | **1.00 / 53 / 26**                               | 0.98 / 7 / 73                                         | -                                                | 0.98 / 325 / 247                                                 | 1.00 / 132 / 436                                       | 1.00 / 50 / 162                                               | -                                                         | 1.00 / 223 / 88                            | -                                                           | 1.00 / 6 / 101                                |
| exact_symbol      | **1.00 / 11 / 26**                               | -                                                     | -                                                | -                                                                | 1.00 / 137 / 436                                       | 1.00 / 10 / 431                                               | 1.00 / 0.09 / 51                                          | 1.00 / 304 / 54                            | 1.00 / 1 / 66                                               | -                                             |
| file_outline      | **1.00 / 33 / 126**                              | -                                                     | -                                                | 0.99 / 321 / 975                                                 | -                                                      | 1.00 / 5 / 795                                                | 1.00 / 0.09 / 183                                         | 0.85 / 101 / 51                            | 1.00 / 6 / 687                                              | -                                             |
| fuzzy_symbol      | 0.99 / 90 / 27                                   | -                                                     | -                                                | -                                                                | -                                                      | **1.00 / 398 / 434**                                          | -                                                         | -                                          | -                                                           | -                                             |
| nohit_search      | 1.00 / 81 / 3                                    | 1.00 / 7 / 30                                         | -                                                | 1.00 / 308 / 47                                                  | **1.00 / 146 / 1**                                     | 1.00 / 55 / 61                                                | -                                                         | 1.00 / 229 / 1                             | -                                                           | 1.00 / 6 / 29                                 |
| references        | **1.00 / 22 / 43**                               | -                                                     | -                                                | -                                                                | -                                                      | 0.28 / 7 / 152                                                | 0.06 / 0.09 / 52                                          | 0.87 / 193 / 651                           | -                                                           | -                                             |
| structural_search | **0.89 / 26 / 31**                               | -                                                     | 0.15 / 348 / 633                                 | -                                                                | -                                                      | -                                                             | -                                                         | -                                          | -                                                           | -                                             |
| substring_search  | **1.00 / 76 / 131**                              | 0.99 / 9 / 292                                        | -                                                | 0.78 / 319 / 862                                                 | 1.00 / 133 / 1012                                      | 0.81 / 46 / 537                                               | -                                                         | 0.94 / 227 / 638                           | -                                                           | 1.00 / 8 / 587                                |

## Docs

- [Installation](docs/installation.md)
- [CLI](docs/cli.md)
- [Host overview](docs/hosts/all-agent-clis.md)
- [MCP SDK](docs/sdk/mcp.md)
- [Troubleshooting](docs/troubleshooting.md)

## License

Apache License 2.0. See [LICENSE](LICENSE).
