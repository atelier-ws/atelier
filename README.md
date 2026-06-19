<!-- cspell:ignore Alamofire Excalidraw ast-grep codegraph ctags django jcodemunch nohit okhttp scip serena tokio vscode zoekt -->

<div align="center">

# Atelier

### The complete runtime for coding agents

**72% cheaper · 74% fewer tokens · 71% faster**

### [Documentation →](https://atelier.ws)

[![License](https://img.shields.io/github/license/atelier-ws/atelier?style=for-the-badge)](https://github.com/atelier-ws/atelier/blob/main/LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/atelier-ws/atelier/tests.yml?style=for-the-badge&label=tests)](https://github.com/atelier-ws/atelier/actions/workflows/tests.yml)
[![Latest release](https://img.shields.io/github/v/release/atelier-ws/atelier?style=for-the-badge)](https://github.com/atelier-ws/atelier/releases)
[![Total downloads](https://img.shields.io/github/downloads/atelier-ws/atelier/total?style=for-the-badge)](https://github.com/atelier-ws/atelier/releases)

[![Claude Code](https://img.shields.io/badge/Claude_Code-supported-CF6D3F.svg)](https://claude.ai/code)
[![Codex](https://img.shields.io/badge/Codex-supported-10A37F.svg)](https://openai.com/codex)
[![opencode](https://img.shields.io/badge/opencode-supported-7C3AED.svg)](https://opencode.ai)

<br/>

**Live savings across all Atelier sessions** &nbsp;·&nbsp; updates on every session end

[![Cost saved](https://img.shields.io/endpoint?url=https%3A%2F%2Fatelier.ws%2Fapi%2Fbadge%3Fmetric%3Dsavings&style=for-the-badge&color=04ba0d)](https://atelier.ws)
[![Tokens less](https://img.shields.io/endpoint?url=https%3A%2F%2Fatelier.ws%2Fapi%2Fbadge%3Fmetric%3Dtokens&style=for-the-badge&color=7904b8)](https://atelier.ws)
[![Calls avoided](https://img.shields.io/endpoint?url=https%3A%2F%2Fatelier.ws%2Fapi%2Fbadge%3Fmetric%3Dcalls&style=for-the-badge&color=eae4ed)](https://atelier.ws)

</div>

---

## Get Started

### 1. Install

```bash
curl -fsSL https://install.atelier.ws | bash
```

### 2. Initialize your project

```bash
cd your-project
atelier init
```

<sub>Already installed? Run `atelier update` to update in place.</sub>

---

## Why Atelier?

- **Grounded code intelligence:** search, file reads, exact symbols, callers, callees, usages, and outlines.
- **Safer agent edits:** deterministic edit tools plus validation-friendly shell access.
- **Local memory:** repo/session recall without requiring a hosted backend.
- **Host-ready packaging:** MCP configs, agents, and skills for popular coding agents.
- **Cost-aware workflow:** benchmark and savings reports from checked-in artifacts.

---

## MCP Tools

| Tool | Use |
| ---- | --- |
| `search` | Semantic + keyword code search across the repo. |
| `grep` | Regex / glob / type-filtered search with token-budgeted output. |
| `read` | Budgeted file reads by outline, range, or full file. |
| `node` | Exact source for a named symbol. |
| `explore` | Directory tree and file listing. |
| `callers` | Find all call sites of a symbol. |
| `callees` | Find all symbols called by a function. |
| `usages` | All references to a symbol across the repo. |
| `codemod` | Structured, pattern-based code transforms. |
| `edit` | Deterministic file edits with optional verify gate. |
| `shell` | Compact command execution when needed. |
| `memory` | Local memory read and recall. |
| `sql` | Query the local index database directly. |
| `web_fetch` | Fetch a public URL and return clean Markdown. |

---

## Agents and Skills

Packaged agents in [integrations/agents/](integrations/agents/):

| Agent    | Subagent         | Writes? | Use                                                              | Details                                                                                                                               |
| -------- | ---------------- | ------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| auto     | atelier:auto     | Yes     | Fully autonomous unattended mode.                                | Runs end to end with no plan approval and no questions. For CI, benchmarks, and headless automation.                                  |
| code     | atelier:code     | Yes     | Main coding mode for edits, refactors, bug fixes, and features.  | Uses Atelier MCP tools for file I/O, search, edits, and shell work; applies shared coding guidelines and validates before concluding. |
| explore  | atelier:explore  | No      | Read-only codebase exploration.                                  | Locates files, symbols, and patterns; reports cited findings; never edits, creates, or deletes files.                                 |
| plan     | atelier:plan     | No      | Grounded implementation planning.                                | Explores enough to produce a concrete plan with files, ordering, validation, risks, and open questions; never edits.                  |
| execute  | atelier:execute  | Yes     | Focused execution of an accepted plan or narrow task.            | Makes the smallest verified code change, self-verifies, and stops for review.                                                         |
| solve    | atelier:solve    | Yes     | Autonomous end-to-end task solving.                              | Produces the required result early, iterates against real checks, and owns completion.                                                |
| review   | atelier:review   | No      | Adversarial code review.                                         | Applies the verification ladder and rubric discipline; reads code directly and never edits source files.                              |
| research | atelier:research | No      | External research.                                               | Fetches web sources, GitHub repos, and package docs; synthesizes with citations; never edits files.                                   |

Packaged skills in [integrations/skills/](integrations/skills/):

`benchmark` · `knowledge` · `orchestrate` · `settings` · `swarms`

---

## Benchmarks

Atelier vs baseline (Claude Code headless, `claude-sonnet-4-6`) across 7 real-world open-source codebases — 5 reps each, median reported. Correctness = mean LLM judge score across reps (0–1). Raw results: [reports/public/benchmark/codebench/](reports/public/benchmark/codebench/)

| Codebase | Language | Cost | Tokens | Time | Judge score |
| -------- | -------- | ---- | ------ | ---- | ----------- |
| VS Code | TypeScript · 11k files · 3.3M lines · 33M tok | 82.1% cheaper | 91.2% fewer | 28% faster | 1.00 |
| Excalidraw | TypeScript · 600 files · 171k lines · 1.7M tok | 62.6% cheaper | 67.1% fewer | 51% faster | 0.94 |
| Django | Python · 3k files · 522k lines · 4.8M tok | 88.1% cheaper | 92.4% fewer | 54% faster | 1.00 |
| Tokio | Rust · 784 files · 176k lines · 1.4M tok | 96.8% cheaper | 96.9% fewer | 97% faster | 0.98 |
| OkHttp | Kotlin/Java · 596 files · 133k lines · 1.1M tok | 84.3% cheaper | 76.1% fewer | 14% faster | 0.98 |
| gin | Go · 99 files · 24k lines · 171k tok | 17.8% cheaper | 17.4% more | 49% slower | 0.94 |
| Alamofire | Swift · 98 files · 44k lines · 452k tok | 48.6% cheaper | 39.5% fewer | 88% faster | 1.00 |
| **Overall, pooled** | **7 repos · 16k files · 4.4M lines · 43M tok** | **72.0% cheaper** | **74.4% fewer** | **71% faster** | **0.98** |

Run CodeBench:

```bash
atelier benchmark codebench \
  --arm baseline --arm atelier \
  --task all \
  --reps 5 \
  --model claude-sonnet-4-6 \
  --cli-driver claude
```

Run local provider/read benchmarks:

```bash
atelier benchmark providers
```

Provider/read benchmark numbers: triplet is `correctness / median tokens / median ms`; `-` means unsupported or not benchmarked.

| Test type         | [atelier](https://github.com/atelier-ws/atelier) | [atelier-zoekt](https://github.com/sourcegraph/zoekt) | [ast-grep](https://github.com/ast-grep/ast-grep) | [code-index-mcp](https://github.com/johnhuang316/code-index-mcp) | [codegraph](https://github.com/colbymchenry/codegraph) | [jcodemunch-mcp](https://github.com/jgravelle/jcodemunch-mcp) | [scip-python](https://github.com/sourcegraph/scip-python) | [serena](https://github.com/oraios/serena) | [universal-ctags](https://github.com/universal-ctags/ctags) | [zoekt](https://github.com/sourcegraph/zoekt) |
| ----------------- | ------------------------------------------------ | ----------------------------------------------------- | ------------------------------------------------ | ---------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------ | ----------------------------------------------------------- | --------------------------------------------- |
| callees           | **1.00 / 78 / 114**                              | -                                                     | -                                                | -                                                                | 0.85 / 112 / 135                                       | 0.97 / 1654 / 283                                             | -                                                         | -                                          | -                                                           | -                                             |
| callers           | **1.00 / 72 / 48**                               | -                                                     | 0.52 / 276 / 342                                 | -                                                                | 0.99 / 204 / 136                                       | 0.53 / 1666 / 201                                             | 0.13 / 59 / 0.09                                          | 0.86 / 450 / 214                           | -                                                           | -                                             |
| exact_search      | **1.00 / 26 / 53**                               | 0.98 / 73 / 7                                         | -                                                | 0.98 / 247 / 325                                                 | 1.00 / 436 / 132                                       | 1.00 / 162 / 50                                               | -                                                         | 1.00 / 88 / 223                            | -                                                           | 1.00 / 101 / 6                                |
| exact_symbol      | **1.00 / 26 / 11**                               | -                                                     | -                                                | -                                                                | 1.00 / 436 / 137                                       | 1.00 / 431 / 10                                               | 1.00 / 51 / 0.09                                          | 1.00 / 54 / 304                            | 1.00 / 66 / 1                                               | -                                             |
| file_outline      | **1.00 / 126 / 33**                              | -                                                     | -                                                | 0.99 / 975 / 321                                                 | -                                                      | 1.00 / 795 / 5                                                | 1.00 / 183 / 0.09                                         | 0.85 / 51 / 101                            | 1.00 / 687 / 6                                              | -                                             |
| fuzzy_symbol      | 0.99 / 27 / 90                                   | -                                                     | -                                                | -                                                                | -                                                      | **1.00 / 434 / 398**                                          | -                                                         | -                                          | -                                                           | -                                             |
| nohit_search      | 1.00 / 3 / 81                                    | 1.00 / 30 / 7                                         | -                                                | 1.00 / 47 / 308                                                  | **1.00 / 1 / 146**                                     | 1.00 / 61 / 55                                                | -                                                         | **1.00 / 1 / 229**                         | -                                                           | 1.00 / 29 / 6                                 |
| references        | **1.00 / 43 / 22**                               | -                                                     | -                                                | -                                                                | -                                                      | 0.28 / 152 / 7                                                | 0.06 / 52 / 0.09                                          | 0.87 / 651 / 193                           | -                                                           | -                                             |
| structural_search | **0.89 / 31 / 26**                               | -                                                     | 0.15 / 633 / 348                                 | -                                                                | -                                                      | -                                                             | -                                                         | -                                          | -                                                           | -                                             |
| substring_search  | **1.00 / 131 / 76**                              | 0.99 / 292 / 9                                        | -                                                | 0.78 / 862 / 319                                                 | 1.00 / 1012 / 133                                      | 0.81 / 537 / 46                                               | -                                                         | 0.94 / 638 / 227                           | -                                                           | 1.00 / 587 / 8                                |

---

## Docs

- [Installation](docs/installation.md)
- [CLI](docs/cli.md)
- [Host overview](docs/hosts/all-agent-clis.md)
- [MCP SDK](docs/sdk/mcp.md)
- [Troubleshooting](docs/troubleshooting.md)

---

## Star History

<a href="https://star-history.com/#atelier-ws/atelier&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=atelier-ws/atelier&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=atelier-ws/atelier&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=atelier-ws/atelier&type=Date" />
  </picture>
</a>

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
