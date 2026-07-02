# 🧱 Built With — Technology & Concepts

Atelier is a single Python runtime (mypyc-compiled for speed) that your coding agent talks to over **MCP**. Every dependency below earns its place against one rule: **spend fewer tokens to reach a more correct answer.** Here is the full stack and the reasoning behind each choice.

### Core language & runtime

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **Python 3.12–3.13** | Implementation language | Ubiquitous in the AI/agent ecosystem; rich parsing, ML, and tooling libraries |
| **mypyc** | Ahead-of-time compiler (typed Python → C extensions) | Hot paths (parsing, ranking, indexing) compile to native code on build (`hatch_build.py`); strict typing pays off twice — correctness *and* speed |
| **Pydantic v2** | Typed models + validation (Rust-backed core) | Every tool request/response, config, and on-disk record is a validated model — schema errors fail fast and cheap |
| **Click** | CLI framework | Powers the `atelier` command tree (~35 command groups) |
| **Rich + prompt-toolkit** | Terminal rendering + interactive prompts | Readable, budget-aware CLI output and the `init`/auth wizards |

### Code intelligence — the grounded layer

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **tree-sitter** + **tree-sitter-language-pack** | Incremental, error-tolerant parsers for 40+ languages | Builds the symbol table, file outlines, and call graph behind `code_search`/`read`/`explore` — language-agnostic, no per-language LSP server required |
| **Call-graph engine** (in-house) | Resolves definitions, callers, callees, usages | Returns the exact symbol and its neighborhood in one call instead of grep-then-read loops — the core of the token savings |
| **rapidfuzz** | Fast fuzzy string matching | Fuzzy symbol lookup and the edit tool's fuzzy anchor matching |
| **diff-match-patch** | Myers diff / patch | Deterministic, conflict-tolerant file edits |
| **rope** | Python refactoring library | Safe symbol rename (the `rename` extra) |
| **GitPython** + **pygit2** (libgit2) | Git plumbing | Repo introspection, history archaeology, and worktree/swarm management — pygit2 for the hot paths |

### Search & retrieval

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **SQLite (+ FTS)** | Embedded, single-file index DB | The local code index, keyword/BM25 search, and the `sql` tool — zero servers, ships with Python |
| **BM25** (in-house ranking) | Lexical relevance scoring | Exact-match relevance for `grep`/`search` and context reuse |
| **blake3** | Cryptographic hash | Content-addressed cache keys → incremental re-indexing touches only what changed |
| **sentence-transformers** + **PyTorch** | Embedding inference | Local semantic code search; ships **BGE-Code-v1**, auto-falls back to **SFR-Embedding-Code-400M** on low VRAM |
| **sqlite-vector** (TurboQuant) | In-DB 4-bit-quantized ANN scan | Large-repo semantic top-K runs *inside* SQLite over quantized vectors — linux's 1.24M×1536 store scans from ~960 MB of quantized data instead of loading a 7.5 GB NumPy matrix into Python (no more OOM); the exact NumPy cosine path stays as a transparent fallback |
| **pgvector** + **NumPy** | Vector similarity / ANN | Postgres-backed or in-process cosine for small/shared repos; NumPy is also the exact fallback under the sqlite-vector scan |
| **psycopg** | PostgreSQL driver | The `postgres` backend for index + analytics at team scale |

### Web & content extraction

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **trafilatura** + **BeautifulSoup** + **markdownify** + **markdown-it-py** | HTML → clean Markdown | `web_fetch` strips nav, scripts, and chrome so only readable content reaches the context window |
| **aiohttp** + **urllib3** + **yarl** | Async HTTP + URL handling | Concurrent fetches and provider calls |
| **regex** | Advanced regex engine | Patterns beyond the stdlib `re` for search and parsing |

### Memory

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **Local memory store (SQLite)** | Default, server-free recall | Repo/session facts and lessons without any hosted backend |
| **Letta (MemGPT)** | Agent memory server | Optional durable cross-session memory and archival recall (`letta-client` talks to it) |

### Token economics & model routing

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **tiktoken** | BPE tokenizer | Exact token counting for budgets, cost tracking, and the live savings badges |
| **LiteLLM** | Multi-provider LLM gateway | Cross-vendor model routing (`route`/`router` commands) |
| **Ollama** | Local LLM runtime | On-device models for "smart" features (summarize/classify) with no API cost |
| **OpenAI SDK** | Cloud LLM client | Optional cloud model calls for routing/cloud features |
| **Google OR-Tools** | Constraint/optimization solver | The budget optimizer — allocating token and cost budget across steps |
| **XGBoost** | Gradient-boosted trees | Learned ranking signals (e.g. PR-risk and rank models) |

### Service, API & daemon

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **FastAPI** + **Uvicorn** | ASGI framework + server | The `atelierd` daemon, local HTTP API, and badge/insights endpoints |

### Reliability & supervision

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **tenacity** | Retry with backoff | Resilient provider and network calls |
| **pybreaker** | Circuit breaker | Tool supervision trips a breaker on repeated failures instead of looping |
| **cryptography** | Signing / verification | Signed license leases verified **offline** against a baked-in public key |

### Observability & telemetry

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **OpenTelemetry** (API / SDK / OTLP) | Vendor-neutral traces + metrics | Every session emits spans/metrics; local-first with a strict allowlist and opt-out |
| **Prometheus client** | Metrics exposition | Runtime metrics endpoint |
| **PostHog + GCP** (sinks) | Product analytics / warehouse | The opt-out telemetry pipeline (OTLP → PostHog + GCP) |
| **Langfuse** | LLM-level tracing | Optional trace-level LLM observability |

### Packaging & distribution

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **MCP SDK** (Model Context Protocol) | Agent ⇄ tool wire protocol | How every host (Claude Code, Codex, Cursor, Copilot, opencode, …) talks to Atelier |
| **hatchling** | Build backend | Wheel builds + force-includes (integrations, lexicons) and the mypyc build hook |
| **PyInstaller** | Portable binary builds | The release distribution (`atelier-distribution-*.tar.gz`) |
| **uv** | Dependency / venv manager | Reproducible installs; the installer runs `uv tool install` |
| **vendored `babel` stub** | Minimal functional shim | `courlan` only needs `Locale.parse(...).language` — Atelier vendors a ~30-line stub instead of the 32 MB real package |

### Monetization backend (proprietary)

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **Cloudflare Workers** | Edge serverless runtime | The `license-issuer` service — global, low-latency |
| **Cloudflare D1** | Edge SQLite database | License and device records |
| **Stripe** | Payments | Checkout → signed purchase credential → entitlement |

### Quality gate (developer tooling)

| Technology | What it is | Why Atelier uses it |
| --- | --- | --- |
| **pytest** (+ xdist, cov, timeout) | Test runner | The suite, parallelized |
| **ruff** + **black** | Lint + format | Style and lint gate |
| **mypy --strict** | Static type checker | Strict typing across `src` (also feeds mypyc) |
| **vulture** | Dead-code detection | Keeps the surface lean |

### Concepts that tighten the loop

- **MCP-native, 5-tool surface** — fewer advertised tools means fewer decisions per turn, so the agent leads with the right primitive.
- **Grounded retrieval over blind reading** — a call graph + symbol index replace grep-and-read navigation.
- **Token budgeting everywhere** — every tool caps and structures output, spilling to disk instead of dumping into context.
- **Hybrid lexical + semantic search** — BM25 for exact matches, embeddings for intent.
- **Content-addressed incremental indexing** — blake3 hashing re-indexes only what changed.
- **Edit-verify gate** — edits run lint/type/test checks before they are accepted.
- **Circuit-broken tool supervision** — repeated failures trip a breaker instead of looping.
- **Host-agnostic packaging** — one runtime, generated MCP configs and personas for every supported agent CLI.
- **Offline-first licensing** — signed leases are verified locally; the network is only touched for enrollment and refresh.
- **mypyc-compiled hot paths** — native speed for parsing, ranking, and indexing.
