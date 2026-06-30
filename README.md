<!-- cspell:ignore Alamofire Excalidraw ast-grep codegraph ctags django jcodemunch nohit okhttp scip serena tokio vscode zoekt -->

<div align="center">

# 🎨 Atelier

## The honest and efficient runtime that makes AI agents cheaper, faster, and more correct

[![Latest release](https://img.shields.io/github/v/release/atelier-ws/atelier?style=flat-square)](https://github.com/atelier-ws/atelier/releases)
[![License: FSL-1.1-ALv2](https://img.shields.io/badge/license-FSL--1.1--ALv2-blue?style=flat-square)](LICENSE)
[![Stars](https://img.shields.io/github/stars/atelier-ws/atelier?style=flat-square)](https://github.com/atelier-ws/atelier)

[![macOS](https://img.shields.io/badge/macOS-supported-blue?style=flat-square)](#)
[![Linux](https://img.shields.io/badge/Linux-supported-blue?style=flat-square)](#)

[![Claude Code](https://img.shields.io/badge/Claude_Code-supported-CF6D3F?style=flat-square)](https://claude.ai/code)
[![Codex](https://img.shields.io/badge/Codex-supported-10A37F?style=flat-square)](https://openai.com/codex)
[![opencode](https://img.shields.io/badge/opencode-supported-7C3AED?style=flat-square)](https://opencode.ai)

<p>
⚡ <b>90% on SWE-bench Verified (50 tasks)</b> &nbsp;·&nbsp;
💰 <b>31.6% cheaper</b> &nbsp;·&nbsp;
🔁 <b>39.4% fewer turns</b> &nbsp;·&nbsp;
🪙 <b>46.4% fewer tokens</b>
</p>

```bash
curl -fsSL https://install.atelier.ws | bash
```

**Live savings across all Atelier sessions** &nbsp;·&nbsp; updates on every session end

Estimated gross savings: input tokens Atelier kept out of context, priced at each model's input / cache-read rates (zero for unknown models). Net end-to-end cost is measured separately under [Benchmarks](#benchmarks).

[![Cost saved](https://img.shields.io/endpoint?url=https%3A%2F%2Fatelier.ws%2Fapi%2Fbadge%3Fmetric%3Dsavings&style=for-the-badge&color=04ba0d)](https://atelier.ws)
[![Tokens less](https://img.shields.io/endpoint?url=https%3A%2F%2Fatelier.ws%2Fapi%2Fbadge%3Fmetric%3Dtokens&style=for-the-badge&color=7904b8)](https://atelier.ws)
[![Calls avoided](https://img.shields.io/endpoint?url=https%3A%2F%2Fatelier.ws%2Fapi%2Fbadge%3Fmetric%3Dcalls&style=for-the-badge&color=eae4ed)](https://atelier.ws)

</div>

---

## 📊 Results

Your AI coding agent is expensive because it reads too much, navigates blindly, and takes twice as many turns as it needs to. Atelier gives it grounded tools — so it spends tokens on thinking, not searching.

<table>
<tr>
<td align="center"><b>🏆 SWE-bench Verified</b><br/><br/><b>90%</b> resolved<br/><sub>vs 80.8% baseline</sub><br/><sub>+9.2 percentage points</sub></td>
<td align="center"><b>💰 Cost</b><br/><br/><b>31.6% cheaper</b><br/><sub>SWE-bench end-to-end</sub><br/><sub>57% cheaper on Exploration tasks</sub></td>
<td align="center"><b>⚡ Speed</b><br/><br/><b>26.4% faster</b><br/><sub>wall-clock per task</sub><br/><sub>39.4% fewer turns</sub></td>
<td align="center"><b>🪙 Tokens</b><br/><br/><b>46.4% fewer</b><br/><sub>SWE-bench end-to-end</sub><br/><sub>cache reads −48% (biggest driver)</sub></td>
</tr>
</table>

> All numbers are end-to-end measured on the same model (`claude-opus-4-8`), same tasks, same environment — not per-tool estimates.

---

## 🎬 Demo

> 📹 Demo GIF coming soon — [watch the benchmark run instead](benchmarks/codebench/results/published)

---

## 🚀 Quick Start

Up and running in 30 seconds.

```bash
# 1. Install
curl -fsSL https://install.atelier.ws | bash

# 2. Init your project (run inside any repo)
cd your-project
atelier init

# Already installed?
atelier update
```

Atelier indexes your repo and wires itself into your coding agent’s MCP config automatically.

---

## 🧠 Why It Works

Vanilla agents navigate by reading entire files and grepping blindly. Atelier replaces that with a grounded tool layer — so agents find what they need in **tens of tokens instead of thousands**.

### 🛠️ MCP Tools

Atelier exposes exactly **5 tools** — not because the others don't exist, but because more tools means more decision overhead. Every extra tool the agent sees is a choice it has to make. `grep`, `search`, `memory`, `sql`, `codemod` and others are all registered and callable by name, but hidden from the advertised surface so the agent leads with the right primitive every time.

| Tool          | What it does                                                         | Why this and not something else                                                                                                                                                |
| --------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `code_search` | Symbol lookup + callers, callees, usages + ranked source in one call | `grep` makes agents loop over results and read whole files. `code_search` returns the exact symbol, its call graph, and the relevant source in one shot — no follow-up needed |
| `read`        | Token-budgeted file reads by outline, range, or full file            | Only needed after`code_search` pinpoints the location. Budget cap prevents agents from pulling entire files when they need three lines                                         |
| `edit`        | Deterministic, verified file edits — multiple files in one call     | CC's`Edit` batches within a single file only. Atelier's `edit` handles cross-file edits in one tool call — fewer round-trips, no create-vs-patch ambiguity                    |
| `bash`        | Shell execution with budgeted, structured output                     | CC's`Bash` dumps the full stdout/stderr into context. Atelier's `bash` caps and structures output so a noisy build log doesn't blow the context window                         |
| `web_fetch`   | Fetch a URL, return clean Markdown                                   | Raw HTML dumps waste thousands of tokens on tags, scripts, and nav chrome. Atelier strips it to readable Markdown — only the content reaches the context window               |

---

## 🤖 Agents & Skills

Atelier ships ready-to-use agent personas and skills — drop them into any supported host.

### Agents

Packaged agents in [integrations/agents/](integrations/agents/). Each covers a distinct phase of the coding loop — explore → plan → execute for human checkpoints, `code` as the all-in-one interactive default, `solve` for autonomous well-defined tasks, `auto` for fully headless runs, and `review`/`research` as read-only specialists that must never write. Removing any one collapses two phases together; adding more creates overlapping choices.

| Agent    | Subagent         | Writes? | Use                                   | Why this and not the default agent                                                                                                             |
| ---------- | ------------------ | --------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| auto     | atelier:auto     | Yes     | Fully autonomous unattended mode      | No plan approval, no questions asked. Use for CI, benchmarks, headless runs where interruptions break the pipeline                             |
| code     | atelier:code     | Yes     | Edits, refactors, bug fixes, features | The default interactive mode. Grounded in Atelier tools, validates before concluding — avoids the "looks done but isn't" failure mode         |
| explore  | atelier:explore  | No      | Read-only codebase exploration        | Hard write-lock. Use when you want answers, not accidental changes. Uses cheaper model.                                                        |
| plan     | atelier:plan     | No      | Implementation planning               | Explores enough to produce a concrete plan with files, ordering, and risks — then stops. Forces the human back into the loop before any edits |
| execute  | atelier:execute  | Yes     | Focused execution of an accepted plan | Narrowest possible change, then stops for review. Use after`plan` when you've approved the approach                                            |
| solve    | atelier:solve    | Yes     | Autonomous end-to-end task solving    | Ships the result early and iterates against real checks. Faster than`code` for well-defined tasks with clear success criteria                  |
| review   | atelier:review   | No      | Adversarial code review               | Read-only by design — can't accidentally "fix" what it's reviewing. Reports cited findings only                                               |
| research | atelier:research | No      | External research                     | Fetches web sources, GitHub repos, package docs. Produces a cited memo — never edits files                                                    |

* Hosts can still spawn other agents as they see fit.

### Skills

Packaged skills in [integrations/skills/](integrations/skills/):

| Skill         | What it does                                                                                                                                                   | Why                                                                                                                                                                                             |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `benchmark`   | Benchmark Atelier vs vanilla Claude Code on your own repo and prompts — real cost, turn, and time deltas with an up-front cost estimate                       | Don’t guess whether Atelier helps your codebase — measure it                                                                                                                                  |
| `orchestrate` | Launch a single structured task and route it to the right execution surface — direct subagent, detached background, or durable workflow with`run_id` tracking | Claude’s Workflow is ephemeral — session ends, run dies. Orchestrate routes to persisted, resumable runs (`pause` / `resume` / `stop` across sessions) or fully detached background execution |
| `perf-review` | Verify a code change against measured performance gates (latency, profiler hot paths, memory/leak, I/O, scaling) — by running it, not reading it              | Performance regressions are invisible in code review — they only show up under measurement                                                                                                     |
| `recall`      | Retrieve what Atelier learned from your past sessions — semantic recall, durable facts, extracted lessons                                                     | Sessions are ephemeral; decisions and context shouldn’t be                                                                                                                                     |
| `swarms`      | Launch multi-worktree swarm runs using Atelier’s existing swarm runtime                                                                                       | Some tasks — migrations, sweeps, parallel experiments — need N agents working simultaneously without stomping on each other                                                                   |
| `ux-review`   | Verify a shipped UI against objective design gates (WCAG, design tokens, responsive integrity, visual regression) — in a real browser                         | Visual bugs and accessibility regressions don’t show up in diffs                                                                                                                               |

---

## 📊 Benchmarks

> 🧾 **One of the most transparent benchmarks in the space.** All 500 individual rep results (50 tasks × 5 reps × 2 arms), per-task costs, turn counts, and correctness flags are committed to this repo. Same model (`claude-opus-4-8`), same Docker image, same tools disabled, same turn cap — both arms. We don't hide the regressions. Raw data: [`benchmarks/codebench/results/swe50_2026_06_30/`](benchmarks/codebench/results/swe50_2026_06_30/)

### Exploration tasks

8 open-source codebases · 5 questions each · `claude-opus-4-8` · costs summed across all 5 prompts (5 reps). Sorted by savings.

| Codebase                                               | Language                                         |  Atelier |  Baseline | Cost ↓ | Δ Input | Δ Cache W | Δ Cache R | Δ Output |
| ------------------------------------------------------ | ------------------------------------------------ | -------: | --------: | ------: | ------: | --------: | --------: | -------: |
| [VS Code](https://github.com/microsoft/vscode)         | TypeScript · 11k files · 3.3M lines · 33M tok  |    $0.85 |     $5.79 | **85%** |   −51k |    −270k |  −2,144k |    −66k |
| [Django](https://github.com/django/django)             | Python · 3k files · 522k lines · 4.8M tok      |    $0.45 |     $2.85 | **84%** |    −8k |    −136k |  −1,248k |    −22k |
| [Tokio](https://github.com/tokio-rs/tokio)             | Rust · 784 files · 176k lines · 1.4M tok       |    $0.47 |     $2.15 | **78%** |    −1k |    −121k |    −522k |     −6k |
| [OkHttp](https://github.com/square/okhttp)             | Java · 596 files · 133k lines · 1.1M tok       |    $0.59 |     $2.23 | **73%** |   −20k |    −102k |    −598k |    −13k |
| [Linux](https://github.com/torvalds/linux)             | C · 95k files · 30M lines · 300M tok           |    $0.70 |     $1.67 | **58%** |   −11k |     −38k |    −448k |    −19k |
| [Gin](https://github.com/gin-gonic/gin)                | Go · 99 files · 24k lines · 171k tok           |    $0.53 |     $1.04 | **49%** |      0k |     −45k |    −300k |      0k |
| [Alamofire](https://github.com/Alamofire/Alamofire)    | Swift · 98 files · 44k lines · 452k tok        |    $1.81 |     $2.41 | **25%** |    −8k |     −49k |      −5k |     +4k |
| [Excalidraw](https://github.com/excalidraw/excalidraw) | TypeScript · 600 files · 171k lines · 1.7M tok |    $5.54 |     $7.23 | **23%** |    −7k |     −79k |  −1,118k |    −19k |
| **Total**                                              | **8 repos · 110k files · 34M lines · 342M tok** | **$10.94** | **$25.37** | **57%** | **−107k** | **−840k** | **−6,383k** | **−141k** |

<details>
<summary>All 40 prompts</summary>

**[VS Code](https://github.com/microsoft/vscode)** · TypeScript

1. How does the extension host communicate with the main process?
2. How does VS Code determine when to activate an extension? Trace the extension activation lifecycle from manifest `activationEvents` through to the extension host calling `activate()`.
3. How does VS Code's Language Server Protocol client work? Trace a completion request (triggered by typing) from the editor through the LSP client to the language server and back to the UI.
4. How does VS Code handle workspace trust? What security boundaries are enforced, and how does the trust state affect extension capabilities and settings?
5. How does VS Code's custom tree view API work? Trace from a `TreeDataProvider` registration through to items being rendered in the sidebar panel.

**[Django](https://github.com/django/django)** · Python

1. How does Django's ORM build and execute a query from a QuerySet?
2. How does Django's ORM build SQL queries? Trace a queryset from Python method calls through query compilation to the final SQL string sent to the database.
3. How does Django's middleware stack work? Trace a request from WSGI entry point through the middleware chain to the view and back.
4. How does Django's template engine render a template? Trace from a template string through parsing, compilation, and context rendering to the final HTML output.
5. How does Django's URL routing work? How does `urlpatterns` resolve an incoming URL path to the correct view function, including namespace handling?

**[Tokio](https://github.com/tokio-rs/tokio)** · Rust

1. How does tokio schedule and run async tasks on its runtime?
2. How does Tokio's work-stealing scheduler work? How are async tasks distributed and stolen across worker threads?
3. How does Tokio's `mpsc` channel work internally? Trace a `send()` through the channel buffer to a `recv()` on the other end, including waker registration.
4. How does `tokio::time::sleep` work? How does Tokio manage its timer wheel and wake tasks when deadlines expire?
5. How does the `tokio::select!` macro work? How does it poll multiple futures simultaneously and handle the case where more than one is ready?

**[OkHttp](https://github.com/square/okhttp)** · Java

1. How does OkHttp process a request through its interceptor chain?
2. How does OkHttp handle HTTP/2 connection multiplexing? How are multiple concurrent streams managed over a single TCP connection?
3. How does OkHttp's interceptor chain work? Trace an HTTP request through the full interceptor stack from application interceptors to the network call and back.
4. How does OkHttp manage its connection pool? How are idle connections tracked, reused, and evicted?
5. How does OkHttp's HTTP cache work? What caching strategy is used and how are `Cache-Control` headers applied to decide whether to use a cached response?

**[Linux](https://github.com/torvalds/linux)** · C

1. How does the Linux kernel's Completely Fair Scheduler (CFS) work? How does it track virtual runtime per task and select the next task to run?
2. How does the Linux kernel handle a page fault? Trace from the hardware exception through the kernel's fault handler to memory mapping resolution.
3. How does Linux's epoll work internally? How does it register file descriptors and wake waiting processes when events arrive, and why does it scale better than `select`/`poll`?
4. How does Linux's RCU (Read-Copy-Update) mechanism work? When is it used instead of a mutex and how does it ensure readers see consistent data without locking?
5. How does Linux's Virtual Filesystem (VFS) layer work? Trace a `read()` syscall from userspace through the VFS inode/dentry cache down to a concrete filesystem driver.

**[Gin](https://github.com/gin-gonic/gin)** · Go

1. How does gin route requests through its middleware chain?
2. How does Gin's router handle path parameters and wildcard segments? How is the radix tree built and traversed to match an incoming request path?
3. How does Gin's middleware chain work? How does `c.Next()` pass control through handlers and what happens when a handler calls `c.Abort()`?
4. How does Gin handle request binding? Trace `c.ShouldBindJSON()` from the raw request body through reflection-based struct population to validation.
5. How does Gin's context pool work? How are `gin.Context` objects allocated, reused across requests, and reset to avoid data leaks?

**[Alamofire](https://github.com/Alamofire/Alamofire)** · Swift

1. How does Alamofire build, send, and validate a request?
2. How does Alamofire handle request retrying and authentication challenges? How does `RequestInterceptor` get invoked when a 401 is received?
3. How does Alamofire's response serialization pipeline work? Trace from a completed `URLSessionTask` through `ResponseSerializer` to the decoded Swift model.
4. How does Alamofire handle multipart form data uploads? How is the multipart body constructed, streamed, and sent to `URLSession`?
5. How does Alamofire's `EventMonitor` protocol work? What events are emitted during a request lifecycle and how can multiple monitors be composed?

**[Excalidraw](https://github.com/excalidraw/excalidraw)** · TypeScript

1. How does Excalidraw render and update canvas elements?
2. How does Excalidraw handle real-time collaboration? What is the synchronization mechanism and how are concurrent edits reconciled?
3. How does Excalidraw implement undo/redo? What data structure tracks history and how are element mutations reversed?
4. How does Excalidraw export to SVG and PNG? Trace the export pipeline from element state to the final file output.
5. How does Excalidraw handle element selection and multi-select? How are hit-testing and selection bounds calculated on the canvas?

</details>

Run CodeBench:

```bash
atelier benchmark codebench \
  --arm baseline --arm atelier \
  --task cg_all \
  --reps 5 \
  --model claude-opus-4-8 \
  --cli-driver claude
```

### SWE benchmark (bug fixing)

End-to-end bug fixing on **[SWE-bench Verified](https://www.swebench.com/)** — **50 instances** across **12 Python repos**, **5 reps** each, `claude-opus-4-8`, run inside each instance's Docker image with official `multi_swe_bench` grading. Both arms run inside the image with the project's conda env activated identically (same setup for both arms). **Resolved** = reps whose patch passes the hidden gold tests. Raw results: [benchmarks/codebench/results/swe50_2026_06_30/](benchmarks/codebench/results/swe50_2026_06_30/)

|              |        Cost | Input tok | Cache Write |  Cache Read | Output tok |   Total tok |       Turns |        Time |       Resolved       |
| -------------- | ------------: | ----------: | ------------: | ------------: | -----------: | ------------: | ------------: | ------------: | :---------------------: |
| **atelier**  | **$160.65** | 1,005,646 |   5,656,067 |  93,038,766 |  2,133,440 |  **101.8M** |   **4,221** |   **10.5h** |  **225 / 250 (90%)**  |
| **baseline** | **$234.84** | 1,110,596 |   6,904,544 | 178,930,411 |  2,986,079 |  **189.9M** |   **6,963** |   **14.1h** | **202 / 250 (80.8%)** |
| **delta**    | **−31.6%** |    −9.4% |     −18.1% | **−48.0%** |    −28.6% | **−46.4%** | **−39.4%** | **−25.5%** |      **+9.2 pp**      |

#### Per-task breakdown (5 reps each)

✅ = all 5 reps correct · 🟡 = partial · ❌ = none. Rep costs ordered rep 1–5.

| Task                               | Baseline (CC) ✓ | Atelier ✓ |       Baseline (CC) total |                                                                Atelier total |                                                                  Save | Baseline (CC) rep costs ($) | Atelier rep costs ($) |  |
| ------------------------------------ | :----------------: | :-----------: | --------------------------: | -----------------------------------------------------------------------------: | ----------------------------------------------------------------------: | ----------------------------------------------------- | -- |
| `astropy__astropy-13398`           |      ❌ 0/5      |   ❌ 0/5   |             $9.65 | $3.57 | ![63.0%](https://img.shields.io/badge/63.0%25-brightgreen?style=flat-square) | $2.91, $1.08, $1.88, $2.36, $1.42 | $0.58, $0.67, $0.70, $0.80, $0.81 |                                                     |  |
| `astropy__astropy-13579`           |      ✅ 5/5      |   ✅ 5/5   |             $2.36 | $2.01 |      ![14.7%](https://img.shields.io/badge/14.7%25-yellow?style=flat-square) | $0.56, $0.46, $0.46, $0.36, $0.51 | $0.31, $0.33, $0.34, $0.51, $0.53 |                                                     |  |
| `astropy__astropy-14369`           |      🟡 4/5      |   ✅ 5/5   |             $5.94 | $4.01 | ![32.4%](https://img.shields.io/badge/32.4%25-brightgreen?style=flat-square) | $0.91, $0.75, $1.44, $1.54, $1.30 | $0.61, $0.76, $0.77, $0.93, $0.95 |                                                     |  |
| `astropy__astropy-8707`            |      ❌ 0/5      |   ❌ 0/5   |             $3.92 | $2.37 | ![39.6%](https://img.shields.io/badge/39.6%25-brightgreen?style=flat-square) | $0.25, $0.75, $0.92, $0.68, $1.32 | $0.34, $0.37, $0.44, $0.60, $0.62 |                                                     |  |
| `django__django-11138`             |      ✅ 5/5      |   ✅ 5/5   |             $6.27 | $4.06 | ![35.3%](https://img.shields.io/badge/35.3%25-brightgreen?style=flat-square) | $1.88, $1.67, $0.83, $1.05, $0.83 | $0.78, $0.80, $0.81, $0.82, $0.85 |                                                     |  |
| `django__django-11333`             |      🟡 1/5      |   ✅ 5/5   |             $0.58 | $0.99 |      ![-70.8%](https://img.shields.io/badge/--70.8%25-red?style=flat-square) | $0.11, $0.10, $0.07, $0.10, $0.20 | $0.18, $0.19, $0.20, $0.21, $0.21 |                                                     |  |
| `django__django-12155`             |      ✅ 5/5      |   ✅ 5/5   |             $0.45 | $0.38 |      ![14.1%](https://img.shields.io/badge/14.1%25-yellow?style=flat-square) | $0.10, $0.10, $0.08, $0.10, $0.08 | $0.06, $0.06, $0.07, $0.09, $0.10 |                                                     |  |
| `django__django-12708`             |      ✅ 5/5      |   ✅ 5/5   |             $3.08 | $1.64 | ![46.8%](https://img.shields.io/badge/46.8%25-brightgreen?style=flat-square) | $0.54, $0.47, $0.52, $0.31, $1.24 | $0.20, $0.26, $0.32, $0.38, $0.49 |                                                     |  |
| `django__django-13128`             |      ✅ 5/5      |   ✅ 5/5   |             $5.88 | $3.01 | ![48.7%](https://img.shields.io/badge/48.7%25-brightgreen?style=flat-square) | $1.12, $1.53, $1.66, $0.75, $0.82 | $0.47, $0.50, $0.53, $0.68, $0.83 |                                                     |  |
| `django__django-13344`             |      🟡 3/5      |   ✅ 5/5   |            $11.78 | $8.06 | ![31.6%](https://img.shields.io/badge/31.6%25-brightgreen?style=flat-square) | $1.80, $3.50, $1.72, $3.00, $1.75 | $1.40, $1.58, $1.67, $1.67, $1.73 |                                                     |  |
| `django__django-13449`             |      ✅ 5/5      |   ✅ 5/5   |             $6.95 | $3.46 | ![50.3%](https://img.shields.io/badge/50.3%25-brightgreen?style=flat-square) | $1.89, $2.61, $1.83, $0.27, $0.35 | $0.46, $0.65, $0.65, $0.85, $0.85 |                                                     |  |
| `django__django-13837`             |      ✅ 5/5      |   ✅ 5/5   |             $2.41 | $2.14 |      ![11.1%](https://img.shields.io/badge/11.1%25-yellow?style=flat-square) | $0.45, $0.46, $0.45, $0.44, $0.60 | $0.37, $0.43, $0.43, $0.45, $0.47 |                                                     |  |
| `django__django-14007`             |      ✅ 5/5      |   ✅ 5/5   |             $2.58 | $1.56 | ![39.5%](https://img.shields.io/badge/39.5%25-brightgreen?style=flat-square) | $0.44, $0.41, $0.47, $0.74, $0.52 | $0.23, $0.30, $0.34, $0.34, $0.35 |                                                     |  |
| `django__django-14376`             |      🟡 2/5      |   ✅ 5/5   |             $1.07 | $1.09 |     ![-2.7%](https://img.shields.io/badge/--2.7%25-orange?style=flat-square) | $0.30, $0.20, $0.13, $0.17, $0.26 | $0.16, $0.18, $0.24, $0.24, $0.27 |                                                     |  |
| `django__django-14631`             |      ✅ 5/5      |   ✅ 5/5   |             $3.92 | $3.23 |      ![17.4%](https://img.shields.io/badge/17.4%25-yellow?style=flat-square) | $0.74, $1.08, $0.63, $0.75, $0.71 | $0.51, $0.61, $0.64, $0.67, $0.81 |                                                     |  |
| `django__django-15128`             |      ✅ 5/5      |   ✅ 5/5   |             $5.74 | $2.14 | ![62.7%](https://img.shields.io/badge/62.7%25-brightgreen?style=flat-square) | $1.77, $0.90, $1.64, $0.97, $0.46 | $0.39, $0.44, $0.44, $0.44, $0.44 |                                                     |  |
| `django__django-15268`             |      ✅ 5/5      |   ✅ 5/5   |             $5.23 | $1.72 | ![67.1%](https://img.shields.io/badge/67.1%25-brightgreen?style=flat-square) | $0.84, $1.06, $1.30, $1.17, $0.87 | $0.29, $0.30, $0.33, $0.36, $0.44 |                                                     |  |
| `django__django-15503`             |      ✅ 5/5      |   ✅ 5/5   |             $4.52 | $2.20 | ![51.4%](https://img.shields.io/badge/51.4%25-brightgreen?style=flat-square) | $0.66, $1.02, $1.09, $0.86, $0.90 | $0.35, $0.35, $0.50, $0.50, $0.50 |                                                     |  |
| `django__django-15957`             |      ✅ 5/5      |   ✅ 5/5   |             $8.13 | $6.43 |      ![20.9%](https://img.shields.io/badge/20.9%25-yellow?style=flat-square) | $1.82, $1.56, $1.63, $1.08, $2.04 | $1.02, $1.12, $1.20, $1.48, $1.61 |                                                     |  |
| `django__django-16560`             |      🟡 4/5      |   ✅ 5/5   |            $10.02 | $7.33 |      ![26.9%](https://img.shields.io/badge/26.9%25-yellow?style=flat-square) | $0.74, $2.69, $2.28, $2.28, $2.03 | $0.98, $1.52, $1.54, $1.56, $1.74 |                                                     |  |
| `matplotlib__matplotlib-14623`     |      🟡 4/5      |   ✅ 5/5   |             $3.08 | $2.19 |      ![28.8%](https://img.shields.io/badge/28.8%25-yellow?style=flat-square) | $0.63, $0.63, $0.74, $0.35, $0.72 | $0.28, $0.40, $0.46, $0.48, $0.57 |                                                     |  |
| `matplotlib__matplotlib-24870`     |      🟡 3/5      |   ✅ 5/5   |             $3.95 | $3.55 |      ![10.2%](https://img.shields.io/badge/10.2%25-yellow?style=flat-square) | $0.81, $0.64, $0.86, $0.93, $0.71 | $0.65, $0.67, $0.73, $0.75, $0.75 |                                                     |  |
| `mwaskom__seaborn-3069`            |      ✅ 5/5      |   ✅ 5/5   |             $7.11 | $3.98 | ![44.0%](https://img.shields.io/badge/44.0%25-brightgreen?style=flat-square) | $1.37, $1.51, $1.52, $1.12, $1.59 | $0.68, $0.77, $0.79, $0.85, $0.90 |                                                     |  |
| `mwaskom__seaborn-3187`            |      🟡 3/5      |   ❌ 0/5   |             $8.05 | $4.22 | ![47.6%](https://img.shields.io/badge/47.6%25-brightgreen?style=flat-square) | $1.01, $1.63, $1.21, $1.93, $2.27 | $0.58, $0.79, $0.80, $1.02, $1.04 |                                                     |  |
| `pallets__flask-5014`              |      ✅ 5/5      |   ✅ 5/5   |             $0.62 | $0.66 |     ![-6.7%](https://img.shields.io/badge/--6.7%25-orange?style=flat-square) | $0.16, $0.15, $0.08, $0.13, $0.10 | $0.12, $0.13, $0.14, $0.14, $0.14 |                                                     |  |
| `psf__requests-2931`               |      🟡 2/5      |   ✅ 5/5   |             $1.10 | $2.41 |    ![-119.6%](https://img.shields.io/badge/--119.6%25-red?style=flat-square) | $0.46, $0.14, $0.10, $0.14, $0.25 | $0.47, $0.47, $0.47, $0.48, $0.53 |                                                     |  |
| `psf__requests-6028`               |      ✅ 5/5      |   ✅ 5/5   |             $1.86 | $1.46 |      ![21.6%](https://img.shields.io/badge/21.6%25-yellow?style=flat-square) | $0.36, $0.34, $0.48, $0.37, $0.32 | $0.23, $0.27, $0.27, $0.34, $0.34 |                                                     |  |
| `pydata__xarray-3095`              |      ✅ 5/5      |   ✅ 5/5   |             $2.50 | $1.21 | ![51.5%](https://img.shields.io/badge/51.5%25-brightgreen?style=flat-square) | $0.36, $0.49, $0.45, $0.70, $0.50 | $0.21, $0.24, $0.24, $0.26, $0.26 |                                                     |  |
| `pydata__xarray-3305`              |      ✅ 5/5      |   ✅ 5/5   |             $2.42 | $1.25 | ![48.2%](https://img.shields.io/badge/48.2%25-brightgreen?style=flat-square) | $0.42, $0.40, $0.35, $0.85, $0.40 | $0.23, $0.24, $0.26, $0.26, $0.26 |                                                     |  |
| `pydata__xarray-3993`              |      ✅ 5/5      |   ✅ 5/5   |             $2.19 | $1.97 |        ![9.9%](https://img.shields.io/badge/9.9%25-yellow?style=flat-square) | $0.42, $0.40, $0.44, $0.52, $0.39 | $0.36, $0.37, $0.41, $0.41, $0.41 |                                                     |  |
| `pylint-dev__pylint-6386`          |      ✅ 5/5      |   ✅ 5/5   |             $5.33 | $3.47 | ![34.8%](https://img.shields.io/badge/34.8%25-brightgreen?style=flat-square) | $1.55, $1.09, $0.94, $0.88, $0.87 | $0.64, $0.69, $0.70, $0.72, $0.73 |                                                     |  |
| `pylint-dev__pylint-6528`          |      ✅ 5/5      |   ✅ 5/5   |             $6.08 | $5.10 |      ![16.1%](https://img.shields.io/badge/16.1%25-yellow?style=flat-square) | $0.61, $0.98, $1.45, $1.70, $1.34 | $0.89, $0.92, $0.97, $1.07, $1.25 |                                                     |  |
| `pylint-dev__pylint-8898`          |      ✅ 5/5      |   ✅ 5/5   |             $4.04 | $3.05 |      ![24.5%](https://img.shields.io/badge/24.5%25-yellow?style=flat-square) | $0.82, $0.94, $0.80, $0.87, $0.61 | $0.40, $0.56, $0.60, $0.69, $0.80 |                                                     |  |
| `pytest-dev__pytest-5787`          |      ✅ 5/5      |   ✅ 5/5   |             $5.99 | $3.80 | ![36.6%](https://img.shields.io/badge/36.6%25-brightgreen?style=flat-square) | $1.31, $1.04, $1.32, $0.95, $1.38 | $0.66, $0.69, $0.77, $0.83, $0.86 |                                                     |  |
| `pytest-dev__pytest-5840`          |      ✅ 5/5      |   ✅ 5/5   |             $3.74 | $2.60 | ![30.5%](https://img.shields.io/badge/30.5%25-brightgreen?style=flat-square) | $0.84, $0.55, $1.05, $0.68, $0.63 | $0.49, $0.50, $0.52, $0.53, $0.56 |                                                     |  |
| `pytest-dev__pytest-6197`          |      ✅ 5/5      |   ✅ 5/5   |             $8.56 | $5.52 | ![35.5%](https://img.shields.io/badge/35.5%25-brightgreen?style=flat-square) | $2.11, $1.47, $1.58, $1.49, $1.90 | $0.86, $0.98, $1.16, $1.20, $1.32 |                                                     |  |
| `pytest-dev__pytest-7490`          |      ✅ 5/5      |   ✅ 5/5   |             $3.80 | $3.39 |      ![10.8%](https://img.shields.io/badge/10.8%25-yellow?style=flat-square) | $1.09, $0.80, $0.56, $0.86, $0.50 | $0.62, $0.62, $0.63, $0.74, $0.78 |                                                     |  |
| `pytest-dev__pytest-8399`          |      ✅ 5/5      |   ✅ 5/5   |             $1.02 | $0.97 |        ![5.1%](https://img.shields.io/badge/5.1%25-yellow?style=flat-square) | $0.15, $0.16, $0.17, $0.16, $0.37 | $0.16, $0.16, $0.21, $0.21, $0.22 |                                                     |  |
| `scikit-learn__scikit-learn-12682` |      ✅ 5/5      |   ✅ 5/5   |             $7.08 | $3.88 | ![45.2%](https://img.shields.io/badge/45.2%25-brightgreen?style=flat-square) | $1.65, $1.38, $1.38, $1.03, $1.64 | $0.61, $0.75, $0.76, $0.88, $0.88 |                                                     |  |
| `scikit-learn__scikit-learn-25102` |      ✅ 5/5      |   ✅ 5/5   |             $9.45 | $3.91 | ![58.6%](https://img.shields.io/badge/58.6%25-brightgreen?style=flat-square) | $2.11, $2.23, $1.30, $1.79, $2.02 | $0.67, $0.70, $0.70, $0.90, $0.94 |                                                     |  |
| `sphinx-doc__sphinx-10673`         |      ✅ 5/5      |   ✅ 5/5   |             $9.92 | $5.72 | ![42.3%](https://img.shields.io/badge/42.3%25-brightgreen?style=flat-square) | $3.06, $1.57, $1.12, $1.94, $2.24 | $1.04, $1.08, $1.12, $1.21, $1.27 |                                                     |  |
| `sphinx-doc__sphinx-8120`          |      🟡 3/5      |   ✅ 5/5   |             $2.09 | $1.30 | ![37.7%](https://img.shields.io/badge/37.7%25-brightgreen?style=flat-square) | $0.18, $0.35, $0.49, $0.61, $0.47 | $0.25, $0.25, $0.26, $0.27, $0.28 |                                                     |  |
| `sphinx-doc__sphinx-8548`          |      🟡 3/5      |   ✅ 5/5   |           $10.46 | $10.89 |     ![-4.0%](https://img.shields.io/badge/--4.0%25-orange?style=flat-square) | $1.61, $2.87, $2.41, $2.16, $1.41 | $1.25, $2.16, $2.21, $2.38, $2.88 |                                                     |  |
| `sphinx-doc__sphinx-8551`          |      ✅ 5/5      |   ✅ 5/5   |             $3.61 | $1.98 | ![45.1%](https://img.shields.io/badge/45.1%25-brightgreen?style=flat-square) | $0.77, $0.93, $0.30, $1.21, $0.39 | $0.33, $0.35, $0.41, $0.41, $0.47 |                                                     |  |
| `sphinx-doc__sphinx-9461`          |      🟡 2/5      |   🟡 1/5   |             $5.06 | $3.76 |      ![25.7%](https://img.shields.io/badge/25.7%25-yellow?style=flat-square) | $2.32, $1.34, $0.78, $0.63, $0.00 | $1.23, $0.35, $0.67, $0.74, $0.77 |                                                     |  |
| `sympy__sympy-12489`               |      🟡 2/5      |   ❌ 0/5   |             $2.79 | $1.40 | ![49.8%](https://img.shields.io/badge/49.8%25-brightgreen?style=flat-square) | $0.28, $0.50, $0.32, $0.81, $0.88 | $0.24, $0.27, $0.27, $0.30, $0.32 |                                                     |  |
| `sympy__sympy-13091`               |      🟡 4/5      |   ✅ 5/5   |             $4.63 | $3.98 |      ![14.0%](https://img.shields.io/badge/14.0%25-yellow?style=flat-square) | $1.14, $0.77, $1.23, $0.64, $0.85 | $0.71, $0.73, $0.77, $0.84, $0.94 |                                                     |  |
| `sympy__sympy-13877`               |      ✅ 5/5      |   ✅ 5/5   |             $2.80 | $1.71 | ![38.8%](https://img.shields.io/badge/38.8%25-brightgreen?style=flat-square) | $0.49, $0.59, $0.53, $0.44, $0.75 | $0.29, $0.33, $0.35, $0.36, $0.38 |                                                     |  |
| `sympy__sympy-13878`               |      🟡 1/5      |   ✅ 5/5   |             $2.55 | $6.43 |    ![-152.2%](https://img.shields.io/badge/--152.2%25-red?style=flat-square) | $0.00, $0.00, $2.55, $0.00, $0.00 | $0.95, $1.01, $1.37, $1.50, $1.60 |                                                     |  |
| `sympy__sympy-14248`               |      🟡 1/5      |   🟡 4/5   |             $2.51 | $3.46 |   ![-37.5%](https://img.shields.io/badge/--37.5%25-orange?style=flat-square) | $0.00, $1.28, $0.00, $0.00, $1.23 | $0.74, $0.77, $0.89, $1.06, $0.00 |                                                     |  |
| **50 tasks**                       |   **202/250**   | **225/250** | **$234.84** | **$160.65** |                                                                    **31.6%** |                                                                       |                                                     |  |

![Cumulative cost — Atelier vs Baseline on SWE-bench Verified — exponential divergence](reports/public/benchmark/codebench/cost_vs_savings_scatter.svg)

Run the SWE benchmark:

```bash
# Atelier arm uses the `atelier:auto` persona.
CODEBENCH_ATELIER_AGENT=atelier:auto \
uv run --project benchmarks python -m benchmarks.codebench.multiswe_run \
  --suite swe-bench-verified \
  --instances $(cat benchmarks/codebench/data/verified.txt) \
  --min-changed-files 1 \
  -a baseline atelier \
  --reps 5 \
  --model claude-opus-4-8 \
  --jobs 8
```

Opt out of the defaults with `CODEBENCH_EDIT_VERIFY=0` (disable the edit-verify gate) or widen the egress allowlist with `CODEBENCH_EGRESS_ALLOW=anthropic.com,amazonaws.com,…`.

#### Benchmark Setup

Every knob below is identical for both arms **unless marked (atelier-only)**: **Model:** `claude-opus-4-8`, default sampling, both arms.

* **Environment:** each instance's official SWE-bench Verified Docker image; the repo's conda env activated identically; agent runs as root (`IS_SANDBOX=1`). Both arms run _in-image_.
* **Reps:** 5 per instance. **Resolved** = reps whose patch passes the hidden gold tests (official `swebench` harness; gold tests are never shown to the agent and gold test files are stripped from the model patch before grading).
* **Turn cap / timeout:** `--max-turns 100`; per-run agent timeout 3600 s.
* **Egress:** hermetic — only `api.anthropic.com` is reachable (no fetching answers, patches, or hints).
* **Disabled tools (both arms):** see Tool parity below.
* **Task set:** 50 SWE-bench Verified instances across 12 Python repos (astropy, django, matplotlib, seaborn, pallets, requests, xarray, pylint, pytest, scikit-learn, sphinx, sympy). List: `benchmarks/codebench/data/verified.txt`.
* **(atelier-only) persona:** `atelier:auto` — lean autonomous persona; it _replaces_ Claude Code's default system prompt (does not stack — see the fixed-cost note).

#### Tool parity (fair comparison)

Both arms run with the **same tools disabled** (`claude --disallowedTools`, applied identically to baseline and Atelier), so neither can stall, ask for help, or fetch the answer:

* **`AskUserQuestion`, `EnterPlanMode`, `ExitPlanMode`** — no stalling on interactive prompts (runs are headless/unattended).
* **`WebFetch`, `WebSearch`** (and Atelier's `mcp__atelier__web_fetch`) — no fetching answers, patches, or hints from the web.
* **`Workflow`, `ScheduleWakeup`** — heavy orchestration tools out of scope for single-instance bug fixing.

These are deferred-loaded (`ToolSearch`), so disabling them costs **neither arm any fixed prompt tokens**.

#### Tool surface & per-tool token counts

Every tool each arm loads, with schema token counts (cl100k proxy, read from the request flows). `Agent` / `Skill` / `ToolSearch` are **identical** Claude Code natives in both arms; heavier tools load on demand via `ToolSearch`.

| Capability | Vanilla | tok | calls | Atelier | tok | calls |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| Shell | `Bash` | 724 | 3,171 | `bash` | 307 | 1,638 |
| Read file | `Read` | 446 | 1,798 | `read` | 222 | 987 |
| Edit file | `Edit` | 255 | 1,444 | `edit` (handles both) | 306 | 711 |
| Create file | `Write` | 173 | — | _(folded into `edit`)_ | — | — |
| Symbol search + call graph | — | — | — | `code_search` | 280 | 544 |
| Web fetch | `WebFetch` | — | disabled¹ | `web_fetch` | 131 | disabled¹ |
| Subagents | `Agent` | 615 | | `Agent` | 615 | |
| Skills | `Skill` | 492 | | `Skill` | 492 | |
| Deferred-load | `ToolSearch` | 376 | | `ToolSearch` | 376 | |
| **Tools total** | | **3,081** | **6,515** | | **2,729** | **3,895** |
| **System prompt** | | **1,610** | | | **715** | |
| **Fixed prefix** | | **4,691** | | | **3,444** | |

¹ `WebFetch` disabled in this benchmark (both arms) — no fetching answers from the web.

Both keep `Agent`/`Skill`/`ToolSearch`, so both reach the same native deferred pool (TodoWrite, Glob, NotebookEdit, Task, …) on demand.

#### Atelier's fixed cost overhead

Atelier trades a small recurring overhead for fewer, better-grounded turns. Measured on SWE-bench Verified (`claude-opus-4-8`, both arms in-image, read from the captured request flows):

* **Atelier’s static prefix is smaller** (per-tool breakdown in the table above): **~3,444 tok vs ~4,691 tok for vanilla Claude Code** — a **27% smaller cold start**. The persona system prompt is leaner (715 vs 1,610 tok) and tool schemas are more compact (2,729 vs 3,081 tok for the advertised surface). Heavy tools (Workflow, ScheduleWakeup, WebSearch, …) are **deferred** — loaded on demand via `ToolSearch` — so they cost ~0 upfront for either arm.
* **The overhead is conversation content, not the prefix.** From turn 1, hooks prepend **~860 tok** of bootstrap / memory / scoped context; over a session Atelier’s richer tool results (`code_search` call graphs, structured `read`, edit-verify diagnostics) push cached content from ~5.7k to ~9.5k tok — **~3,750 extra tokens re-read each turn**.
* **Per-turn cost ≈ $0.036 vs $0.034 for the baseline** (+6% per turn) — slightly richer context and more structured output per turn.
* **Why Atelier costs more on cheap tasks:** the ~860 tok bootstrap is a fixed floor paid every run regardless of task size. On runs where baseline costs ≤ $0.50 (84 of 250 reps), Atelier averaged **+$0.115 more** per run (~42% premium). The break-even is **~$0.49/task** — roughly **~16 baseline turns** or **~6.5k Opus 4.8 output tokens** per run.
* **Net:** Atelier converges in **median 15 turns vs 27** for the baseline (−44%). On substantive tasks the turn reduction outweighs the per-turn overhead, producing the savings above. Budget a **~$0.10–0.12 floor per task** regardless of size.

### Terminal-Bench

Agentic terminal tasks on **[Terminal-Bench 2.1](https://www.tbench.ai/leaderboard/terminal-bench/2.1)** — the official **89-task** suite, run through the **[Harbor](https://www.harborframework.com/)** harness. The Atelier arm is the `atelier:auto` persona loaded into Claude Code via `--plugin-dir`; both arms run **`claude-opus-4-8`** at **high effort** with **fixed (default) per-task timeouts** and **5 attempts** (`-k 5`) — matching Anthropic's official Opus 4.8 setup (System Card §8.3). The agent runs as root (`IS_SANDBOX=1`) in each throwaway task container, with full trajectories captured (`--output-format stream-json`). Disabled tools: `AskUserQuestion`/`ExitPlanMode` (no stalling on prompts), `WebFetch`/`WebSearch`/`mcp__atelier__web_fetch` (no answer-fetching), `Workflow`/`ScheduleWakeup` (token-heavy).

Auth uses Claude **subscription OAuth tokens** (not API keys), in `benchmarks/harbor/.env`. Each present token gets `ATELIER_BENCH_TOKEN_SLOTS` (default 6) concurrent slots — run `-n 6` with one token, `-n 12` with two:

```bash
# benchmarks/harbor/.env
CLAUDE_CODE_OAUTH_TOKEN_1=sk-ant-oat01-...
# CLAUDE_CODE_OAUTH_TOKEN_2=sk-ant-oat01-...   # optional second subscription
ATELIER_BENCH_MODEL=claude-opus-4-8
```

Build the portable Atelier bundle (pure-Python, old-glibc, reused across every task image), then swap it in:

```bash
docker run --rm -v "$PWD":/atelier:ro -v /tmp/avbuild:/out \
  debian:bullseye-slim bash /atelier/benchmarks/harbor/rebuild_bundle.sh
mv -f /tmp/avbuild/atelier-bundle-new.tar.gz /tmp/avbuild/atelier-bundle.tar.gz
```

Zero-LLM preflight — validates install + code index + the exact `claude` flags on a real task image, **without spending any AI credits**:

```bash
docker run --rm -v "$PWD":/atelier:ro \
  -v /tmp/avbuild/atelier-bundle.tar.gz:/atelier-bundle.tar.gz:ro \
  alexgshaw/adaptive-rejection-sampler:20251031 \
  bash /atelier/benchmarks/harbor/setup_preflight.sh adaptive-rejection-sampler
# -> RESULT:...:PASS node=... cmdprobe=ok idx_git=2 idx_nogit=1 emptyrc=0 logs_agent=ok
```

Run the benchmark — Atelier arm, then the baseline (timeouts stay at the default `1.0` multiplier, per the leaderboard rule):

```bash
set -a; . benchmarks/harbor/.env; set +a
MOUNTS='[{"type":"bind","source":"'"$PWD"'","target":"/atelier","read_only":true},{"type":"bind","source":"/tmp/avbuild/atelier-bundle.tar.gz","target":"/atelier-bundle.tar.gz","read_only":true}]'

# Atelier arm
uv run --no-sync harbor run -d terminal-bench/terminal-bench-2-1 \
  --agent-import-path benchmarks.harbor.atelier_agent:AtelierClaudeCodeHarborAgent \
  --mounts "$MOUNTS" -k 5 -n 6 -o benchmarks/jobs/atelier -y

# Baseline arm — vanilla Claude Code, same model/effort, no Atelier plugin
uv run --no-sync harbor run -d terminal-bench/terminal-bench-2-1 \
  --agent-import-path benchmarks.harbor.atelier_agent:AtelierClaudeCodeHarborAgent \
  --mounts "$MOUNTS" --ak bench_mode=off -k 5 -n 6 -o benchmarks/jobs/baseline -y
```

Resume rate-limited or incomplete trials in place with `harbor job resume -p <job-dir>`.

Run local provider/read benchmarks:

```bash
atelier benchmark providers
```

Provider/read benchmark numbers: triplet is `correctness / median tokens / median ms`; `-` means unsupported or not benchmarked.

| Test type         | [atelier](https://github.com/atelier-ws/atelier) | [atelier-zoekt](https://github.com/sourcegraph/zoekt) | [ast-grep](https://github.com/ast-grep/ast-grep) | [code-index-mcp](https://github.com/johnhuang316/code-index-mcp) | [codegraph](https://github.com/colbymchenry/codegraph) | [jcodemunch-mcp](https://github.com/jgravelle/jcodemunch-mcp) | [scip-python](https://github.com/sourcegraph/scip-python) | [serena](https://github.com/oraios/serena) | [universal-ctags](https://github.com/universal-ctags/ctags) | [zoekt](https://github.com/sourcegraph/zoekt) |
| ------------------- | -------------------------------------------------- | ------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------ | -------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------- | ----------------------------------------------- |
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

### Semantic code search (embedder MRR)

Pure retrieval quality across **14 open-source repos**, balanced at **100 queries per repo** per gold type (1,400 def + 1,400 content + 520 semantic = 3,320 total). Each query is embedded and ranked against all symbols in the repo by cosine similarity; MRR = mean reciprocal rank of the correct symbol.

> Atelier ships **BGE-Code-v1** (`BAAI/bge-code-v1`) as the default semantic embedder — best avg MRR at ~1.5B params and 6× faster indexing throughput than the next-closest model.

| Model                      | Params | Def MRR   | Content MRR | Semantic MRR | **Avg**   |
| ---------------------------- | -------- | ----------- | ------------- | -------------- | ----------- |
| **BGE-Code-v1** ✦ default | ~1.5B  | 0.768     | **0.817**   | **0.773**    | **0.786** |
| GTE-Qwen2-1.5B             | ~1.5B  | **0.771** | 0.812       | 0.767        | 0.783     |
| Nomic-embed-code 3584d     | ~7B    | 0.756     | 0.798       | 0.755        | 0.770     |
| Nomic-embed-code 768d      | ~7B    | 0.746     | 0.785       | 0.746        | 0.759     |
| SFR-Embedding-Code-400M    | 400M   | 0.738     | 0.791       | 0.742        | 0.757     |
| Qwen3-Embedding-0.6B       | 600M   | 0.728     | 0.776       | 0.727        | 0.744     |
| Qwen3-Embedding-4B         | ~4B    | 0.724     | 0.775       | 0.726        | 0.742     |
| BGE-M3                     | 570M   | 0.684     | 0.746       | 0.704        | 0.711     |
| Arctic-Embed-L-v2          | 568M   | 0.639     | 0.704       | 0.663        | 0.669     |

Repos: astropy · atelier · django · flask · linux · matplotlib · pylint · pytest · requests · scikit-learn · seaborn · sphinx · sympy · xarray. Gold sets: [`benchmarks/codebench/data/`](benchmarks/codebench/data/).

Override the embedder:

```bash
# use a different model
ATELIER_CODE_EMBEDDER=hf ATELIER_CODE_EMBED_MODEL=Alibaba-NLP/gte-Qwen2-1.5B-instruct atelier index

# run the sweep yourself
python3 benchmarks/codebench/run_embedder_sweep.py
```

---

## 📚 Docs

* [Installation](docs/installation.md)
* [CLI reference](docs/cli.md)
* [Host setup (all agent CLIs)](docs/hosts/all-agent-clis.md)
* [MCP SDK](docs/sdk/mcp.md)
* [Troubleshooting](docs/troubleshooting.md)

---

## ⭐ Star History

<a href="https://star-history.com/#atelier-ws/atelier&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=atelier-ws/atelier&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=atelier-ws/atelier&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=atelier-ws/atelier&type=Date" />
  </picture>
</a>

---

## 📄 License

[FSL-1.1-ALv2](LICENSE) — the Functional Source License: source-available and free for any
Permitted Purpose, converting to Apache 2.0 two years after each release. The one carve-out is
a _Competing Use_ (a commercial product or service that competes with Atelier). The
`services/license-issuer/` backend is proprietary and licensed separately under its own `LICENSE`.
