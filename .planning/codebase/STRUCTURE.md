# Structure

**Analysis Date:** 2025-05-25

## Directory Layout

```
atelier/                          # repo root
├── src/atelier/                  # Python package (all runtime code)
│   ├── gateway/                  # entry points — thin dispatchers only
│   │   ├── adapters/             # MCP server, CLI, ecosystem adapters, runtime façade
│   │   ├── cli/                  # CLI sub-module helpers
│   │   ├── hosts/                # host-specific session parsers + configs
│   │   ├── integrations/         # external analytics, Langfuse, ledger reconstructor
│   │   └── sdk/                  # AtelierClient SDK (local / mcp / remote)
│   ├── core/                     # domain logic — no infra/gateway imports
│   │   ├── capabilities/         # 30+ capability modules (see below)
│   │   ├── foundation/           # Pydantic models, store, retriever, renderer, paths
│   │   ├── runtime/              # AtelierRuntimeCore orchestrator (engine.py)
│   │   ├── service/              # FastAPI HTTP API surface
│   │   ├── domains/              # domain-specific logic + builtin domain loader
│   │   ├── improvement/          # failure analyzer
│   │   └── rubrics/              # YAML rubric definitions
│   ├── infra/                    # persistence + integrations — depends on core
│   │   ├── storage/              # SQLite / Postgres / vector stores
│   │   ├── runtime/              # RunLedger, Checkpoint, RealtimeContext, CostTracker
│   │   ├── code_intel/           # SCIP, ast-grep, Zoekt, git history, cross-lang
│   │   ├── embeddings/           # local / OpenAI / Letta embedders
│   │   ├── memory_bridges/       # Letta, OpenMemory adapters
│   │   ├── internal_llm/         # internal LLM routing
│   │   ├── tree_sitter/          # AST parsing helpers
│   │   ├── benchmarks/           # benchmark harnesses
│   │   └── seed_blocks/          # seed memory block data
│   └── sdk/                      # public SDK (thin __init__.py)
├── frontend/                     # React/Vite dashboard
│   ├── src/                      # React components + api.ts
│   └── public/                   # static assets
├── integrations/                 # host integrations (not in Python package)
│   ├── claude/plugin/            # Claude Code plugin + hooks
│   ├── codex/                    # Codex integration
│   ├── copilot/                  # GitHub Copilot integration
│   ├── opencode/                 # OpenCode integration
│   ├── antigravity/              # Antigravity integration
│   └── skills/                   # agent skills
├── tests/                        # test suite mirroring src layout
│   ├── core/                     # core layer tests
│   ├── gateway/                  # gateway layer tests
│   ├── infra/                    # infra layer tests
│   ├── benchmarks/               # A/B benchmark tests (marked slow)
│   ├── fixtures/                 # shared test fixtures
│   ├── golden/                   # golden output files
│   └── docs/                     # doc-governance tests
├── docs/                         # documentation
│   ├── architecture/             # layers.md, domain-map.md, README.md
│   ├── agent-os/                 # agent operating rules (source of truth)
│   ├── specs/                    # feature execution specs
│   ├── decisions/                # architectural decision records
│   ├── plans/                    # execution plans
│   └── quality/                  # scorecard, debt tracking
├── scripts/                      # operational scripts
│   ├── install_claude.sh         # Claude plugin install
│   └── verify_*.sh               # verification scripts
├── pyproject.toml                # Python package config (uv)
├── Makefile                      # lint, format, typecheck, test, docs targets
├── CLAUDE.md                     # Claude Code working instructions
├── AGENTS.md                     # generated agent instructions (from docs/agent-os/)
├── Dockerfile.api                # API service Docker image
├── Dockerfile.frontend           # Frontend Docker image
└── docker-compose.yml            # local dev stack
```

## Key Files

### Entry Points
| File | Purpose |
|------|---------|
| `src/atelier/gateway/adapters/mcp_server.py` | stdio MCP server (4855 lines) — primary agent interface |
| `src/atelier/gateway/adapters/cli.py` | `atelier` CLI (8988 lines — largest file) |
| `src/atelier/core/service/api.py` | FastAPI HTTP service (5812 lines) |
| `src/atelier/gateway/adapters/runtime.py` | `ContextRuntime` in-process façade |
| `src/atelier/gateway/adapters/adapter_base.py` | Base class for all ecosystem adapters |

### Orchestration
| File | Purpose |
|------|---------|
| `src/atelier/core/runtime/engine.py` | `AtelierRuntimeCore` — capability orchestrator (940 lines) |
| `src/atelier/core/foundation/store.py` | `ContextStore` — SQLite block/trace/fact store (1824 lines) |
| `src/atelier/infra/runtime/run_ledger.py` | `RunLedger` — append-only event ledger |
| `src/atelier/infra/runtime/checkpoint.py` | `Checkpoint` — resumable execution snapshots |
| `src/atelier/infra/runtime/realtime_context.py` | `RealtimeContextManager` — rolling context minimizer |
| `src/atelier/infra/runtime/cost_tracker.py` | `CostTracker` — per-call cost accumulation |

### Core Foundation
| File | Purpose |
|------|---------|
| `src/atelier/core/foundation/models.py` | Core Pydantic models: `Trace`, `ReasonBlock`, `LedgerEvent`, etc. |
| `src/atelier/core/foundation/memory_models.py` | `MemoryBlock`, `ArchivalPassage` |
| `src/atelier/core/foundation/routing_models.py` | `RouteDecision`, `StepType`, `TaskType` |
| `src/atelier/core/foundation/retriever.py` | `retrieve()`, `score_block()`, `count_tokens()` |
| `src/atelier/core/foundation/renderer.py` | `render_context_for_agent()`, `render_block_markdown()` |
| `src/atelier/core/foundation/rubric_gate.py` | `run_rubric()` — YAML rubric evaluator |
| `src/atelier/core/foundation/paths.py` | `default_store_root()`, `resolve_workspace_root()` |
| `src/atelier/core/foundation/watchdog_profiles.py` | `active_watchdog_weights()` per-domain config |
| `src/atelier/core/foundation/extractor.py` | `extract_candidate()` — extract CandidateBlock from output |

### Capabilities (each in its own subdirectory)
| Path | Class | Size |
|------|-------|------|
| `src/atelier/core/capabilities/code_context/engine.py` | Code intelligence engine | 6291 lines |
| `src/atelier/core/capabilities/context_reuse/capability.py` | `ContextReuseCapability` | 983 lines |
| `src/atelier/core/capabilities/semantic_file_memory/capability.py` | `SemanticFileMemoryCapability` | 627 lines |
| `src/atelier/core/capabilities/plugin_runtime.py` | Plugin execution runtime | 1918 lines |
| `src/atelier/core/capabilities/context_compression/capability.py` | `ContextCompressionCapability` | — |
| `src/atelier/core/capabilities/model_routing/router.py` | `ModelRouter` 5-tier routing | — |
| `src/atelier/core/capabilities/prefix_cache/planner.py` | `PrefixCachePlanner` | — |
| `src/atelier/core/capabilities/prefix_cache/diagnostics.py` | `PrefixCacheDiagnostics` | — |
| `src/atelier/core/capabilities/proof_gate/capability.py` | `ProofGateCapability` | — |
| `src/atelier/core/capabilities/quality_router/capability.py` | `QualityRouterCapability` | — |
| `src/atelier/core/capabilities/tool_supervision/capability.py` | `ToolSupervisionCapability` | — |
| `src/atelier/core/capabilities/loop_detection/capability.py` | `LoopDetectionCapability` | — |
| `src/atelier/core/capabilities/failure_analysis/capability.py` | `FailureAnalysisCapability` | — |
| `src/atelier/core/capabilities/archival_recall/capability.py` | `ArchivalRecallCapability` | — |
| `src/atelier/core/capabilities/prompt_compilation/compiler.py` | `compile_prompt` | — |
| `src/atelier/core/capabilities/pricing.py` | `usage_cost_usd()` | — |
| `src/atelier/core/capabilities/pricing.yaml` | Model cost table | — |

### Storage
| File | Purpose |
|------|---------|
| `src/atelier/infra/storage/factory.py` | `make_memory_store()` — selects SQLite or Postgres |
| `src/atelier/infra/storage/sqlite_store.py` | Default SQLite backend |
| `src/atelier/infra/storage/postgres_store.py` | Production Postgres backend (1235 lines) |
| `src/atelier/infra/storage/memory_store.py` | `MemoryStore` abstract base |
| `src/atelier/infra/storage/vector.py` | Vector similarity search |
| `src/atelier/infra/embeddings/factory.py` | `make_embedder()` — selects embedder |

### Ecosystem Adapters
| File | Purpose |
|------|---------|
| `src/atelier/gateway/adapters/langgraph_adapter.py` | LangGraph nodes/edges integration |
| `src/atelier/gateway/adapters/aider_adapter.py` | Aider integration |
| `src/atelier/gateway/adapters/continue_adapter.py` | Continue.dev integration |
| `src/atelier/gateway/adapters/sweagent_adapter.py` | SWE-agent integration |
| `src/atelier/gateway/adapters/openhands_adapter.py` | OpenHands integration |
| `src/atelier/gateway/sdk/client.py` | `AtelierClient` — main SDK client |
| `src/atelier/gateway/sdk/local.py` | Local (in-process) client |
| `src/atelier/gateway/sdk/mcp.py` | MCP-based client |
| `src/atelier/gateway/sdk/remote.py` | Remote HTTP client |

### Rubrics
| File | Purpose |
|------|---------|
| `src/atelier/core/rubrics/rubric_code_change.yaml` | Rubric for code changes |
| `src/atelier/core/rubrics/rubric_state_change_safety.yaml` | Safety gate for state changes |
| `src/atelier/core/rubrics/rubric_debugging_task.yaml` | Debugging task rubric |
| `src/atelier/core/rubrics/rubric_verification_ladder.yaml` | Verification ladder rubric |
| `src/atelier/core/rubrics/rubric_code_review.yaml` | Code review rubric |
| `src/atelier/core/rubrics/rubric_knowledge_authoring.yaml` | Knowledge authoring rubric |
| `src/atelier/core/rubrics/rubric_change_gate_discipline.yaml` | Change gate discipline |
| `src/atelier/core/rubrics/rubric_source_of_truth_change.yaml` | Source of truth change |
| `src/atelier/core/rubrics/rubric_atelier_retrieval_recall.yaml` | Retrieval recall quality |

### Claude Code Integration
| File | Purpose |
|------|---------|
| `integrations/claude/plugin/hooks/session_start.py` | Session metadata capture |
| `integrations/claude/plugin/hooks/pre_tool_use.py` | Pre-tool savings tracking |
| `integrations/claude/plugin/hooks/post_tool_use.py` | Post-tool savings tracking |
| `integrations/claude/plugin/hooks/stop.py` | Session stats display + auto-record |
| `integrations/claude/plugin/hooks/session_telemetry.py` | Per-tool telemetry → live_savings_events.jsonl |
| `scripts/install_claude.sh` | Stages and installs the Claude plugin |

### Configuration & Build
| File | Purpose |
|------|---------|
| `pyproject.toml` | Package deps, ruff/mypy config, entry points |
| `Makefile` | `lint`, `format`, `typecheck`, `test`, `pre-commit`, `sync-agent-context` |
| `CLAUDE.md` | Working instructions for Claude Code (authoritative) |
| `AGENTS.md` | Generated from `docs/agent-os/` — do NOT edit directly |

## Module Responsibilities

### `gateway/adapters/`
**Dispatchers only.** No business logic. Responsibilities:
- Protocol handling (stdio JSON-RPC for MCP, Click commands for CLI)
- Tool registration and schema derivation (`@mcp_tool` decorator)
- Lazy singleton initialization of core/infra objects
- Session lifecycle management (`_emit_mcp_session_start/end`)
- Auto-compact monitoring and handover advisories
- Savings event emission to `live_savings_events.jsonl`

### `gateway/hosts/`
Host-specific session parsers and configurations. Contains session import parsers for Claude Code, Copilot, Codex with `session_parsers/_session_parser.py` (2133 lines) as the base.

### `gateway/integrations/`
- `external_analytics.py` (911 lines) — savings metrics, cost analytics
- `langfuse.py` — LLM observability telemetry
- `ledger_reconstructor.py` — rebuild ledger from session events
- `openmemory.py` — OpenMemory bridge

### `gateway/sdk/`
`AtelierClient` in three modes — `local` (in-process), `mcp` (stdio), `remote` (HTTP). Used by all ecosystem adapters.

### `core/capabilities/`
Pure domain logic. Each capability is a class with no state except what is injected at construction (store, root path). Capabilities are lazy-loaded via `__getattr__` in `__init__.py`. New capabilities MUST go here, not in gateway code.

### `core/foundation/`
Shared data contracts and utilities used by all capabilities:
- Pydantic models for all cross-layer data
- `ContextStore` — the single source of truth for persisted blocks
- Token budget enforcement
- Rendering and retrieval utilities

### `core/service/`
FastAPI application factory (`create_app()`). Bearer auth, request/response schemas, worker jobs, usage sync, telemetry. Started by `atelier runtime start`.

### `core/rubrics/`
YAML rubrics evaluated by `rubric_gate.run_rubric()`. Loaded at runtime by the rubric loader in `core/domains/loader.py`.

### `infra/storage/`
Two backends selectable at runtime via `factory.py`:
- `sqlite_store.py` — default for local/dev use
- `postgres_store.py` — production multi-tenant use
Both implement the same base interface in `base.py`.

### `infra/runtime/`
Stateful runtime artifacts:
- `RunLedger` — append-only event log for one session
- `Checkpoint` — content-addressed step snapshot for resumability
- `RealtimeContextManager` — rolling signal compressor for next-call context
- `CostTracker` — per-call USD cost accumulation
- `SessionReport` — end-of-session summary
- `OutcomeCapture` — records agent outcomes for learning

### `infra/code_intel/`
Code intelligence stack:
- `scip/` — semantic code index navigation
- `astgrep/` — structural AST search
- `zoekt/` — full-text code search
- `git_history/` — blame, log, diff analysis
- `cross_lang/` — multi-language symbol resolution

## Naming Conventions

### Files
- `capability.py` — primary class file for each capability module (e.g., `context_compression/capability.py`)
- `models.py` — Pydantic models scoped to that module
- `factory.py` — factory functions (`make_*`)
- `_common.py`, `_session_parser.py` — shared/base implementations (underscore prefix)
- `AGENT_README.md` — per-directory guidance for AI agents navigating that module

### Classes
- `*Capability` — all capability classes (e.g., `ContextCompressionCapability`)
- `*Store` — storage backends (`ContextStore`, `MemoryStore`, `SqliteStore`)
- `*Adapter` — ecosystem adapters (`LangGraphAdapter`, `AiderAdapter`)
- `*Manager` — stateful managers (`RealtimeContextManager`)

### Functions
- `make_*` — factory functions (`make_embedder`, `make_memory_store`)
- `render_*` — rendering functions (`render_context_for_agent`, `render_block_markdown`)
- `_get_*` / `_*` — private/internal functions (underscore prefix)
- `tool_*` — MCP tool handler functions in `mcp_server.py`

### Tests
- Mirror `src/atelier/` structure under `tests/`
- `tests/gateway/test_mcp_tool_handlers.py` — MCP tool handler tests
- `tests/gateway/test_p0_mcp_surfaces.py` — P0 MCP surface coverage
- `tests/core/test_code_context.py` — code intelligence engine tests
- Slow tests marked with `@pytest.mark.slow` (excluded from default run)

## Where to Add New Code

### New Capability
1. Create directory: `src/atelier/core/capabilities/<name>/`
2. Create `capability.py` with the `<Name>Capability` class
3. Create `models.py` for capability-specific Pydantic models
4. Create `AGENT_README.md` with module guidance
5. Register in `src/atelier/core/capabilities/__init__.py` via `__getattr__` lazy loading
6. Expose in `AtelierRuntimeCore.__init__` in `src/atelier/core/runtime/engine.py`
7. Tests in `tests/core/test_<name>.py`

### New MCP Tool
1. Add `@mcp_tool(name="<name>", description="...")` decorated function in `src/atelier/gateway/adapters/mcp_server.py`
2. Delegate immediately to a capability or foundation function — no logic in the handler
3. Add tests in `tests/gateway/test_mcp_tool_handlers.py`

### New CLI Command
1. Add `@click.command()` in `src/atelier/gateway/adapters/cli.py`
2. Support `--json` flag for machine-readable output
3. Delegate to SDK/core, not to infra directly

### New Ecosystem Adapter
1. Create `src/atelier/gateway/adapters/<name>_adapter.py`
2. Extend `AgentAdapter` from `adapter_base.py`
3. Use `AtelierClient` from `gateway/sdk/` for all capability calls

### New Storage Migration
1. Add migration SQL in `src/atelier/infra/storage/migrations/`
2. Update both `sqlite_store.py` and `postgres_store.py`

### New Rubric
1. Add `rubric_<name>.yaml` to `src/atelier/core/rubrics/`
2. Reference by ID in `run_rubric(rubric_id="rubric_<name>", checks={...})`

## Runtime State Paths

All runtime state lives under `~/.atelier/` (or `$ATELIER_ROOT`):

| Path | Contents |
|------|---------|
| `runs/<session_id>.json` | RunLedger — events, traces, token stats |
| `session_stats/<uuid>.json` | Per-session savings (Claude Code UUID keyed) |
| `live_savings_events.jsonl` | Append-only savings event log |
| `workspaces/<hash>/session_state.json` | Hook-to-hook workspace state |
| `smart_state.json` | Cumulative savings counters |
| `checkpoints/<session_id>/<step_id>.json` | Resumable execution checkpoints |
| `runtime/realtime_context.json` | Rolling next-call context pack |

---

*Structure analysis: 2025-05-25*
