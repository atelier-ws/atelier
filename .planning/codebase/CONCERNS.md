# Codebase Concerns

**Analysis Date:** 2026-06-02

## Tech Debt

**Very large multi-responsibility modules:**
- Issue: several core files are thousands of lines long, combining orchestration, transport, and policy logic.
- Files: `src/atelier/core/capabilities/code_context/engine.py` (~7.3k LOC), `src/atelier/core/service/api.py` (~6.5k LOC), `src/atelier/gateway/adapters/mcp_server.py` (~6.0k LOC).
- Impact: higher review burden, fragile refactors, slower onboarding, and a large blast radius for small behavior changes.
- Fix approach: extract narrower submodules by responsibility without breaking public surfaces.

**Generated-surface governance is easy to bypass accidentally:**
- Issue: host instruction/install artifacts in `integrations/` are generated from `docs/agent-os/`, but the repo also contains the generated files.
- Files: `docs/agent-os/`, `integrations/`, `scripts/sync_agent_context.py`, `Makefile`.
- Impact: direct edits to generated files can drift from source-of-truth content.
- Fix approach: keep regeneration/check commands in the normal review loop and avoid manual edits to generated surfaces.

**Imported session traces are still partially TODO-backed:**
- Issue: session ingest paths still note missing persistence of reconstructed ledger events as traces.
- Files: `src/atelier/core/service/ingest_session.py`, `src/atelier/core/service/ingest_session_directory.py`.
- Impact: imported sessions may not produce the same trace fidelity as native runtime execution.
- Fix approach: implement the TODOs and cover them with importer regression tests.

## Known Bugs

**No explicit bug registry in-repo:**
- Observation: the static scan did not find a dedicated bug backlog file or many `FIXME` markers; most operational knowledge appears to live in tests/reports instead.
- Files checked: `src/`, `tests/`, `reports/`.
- Impact: regressions may be harder to triage because bug history is dispersed across tests and artifacts.

**Optional integration failures can be hidden behind fail-open behavior:**
- Observation: observability/integration modules intentionally swallow exceptions to protect the core loop.
- Files: `src/atelier/gateway/integrations/langfuse.py`, `src/atelier/gateway/integrations/openmemory.py`.
- Impact: broken observability or sidecars may go unnoticed until a user checks diagnostics.

## Security Considerations

**Service auth defaults to off for local runs:**
- Risk: binding the service on a non-loopback interface without enabling auth would expose powerful runtime endpoints.
- Files: `src/atelier/core/service/auth.py`, `src/atelier/core/service/api.py`, `docker-compose.yml`, `.env.production.example`.
- Current mitigation: API code warns about non-loopback exposure and production env examples enable auth.
- Recommendation: treat `ATELIER_REQUIRE_AUTH=true` + `ATELIER_API_KEY` as mandatory outside local-only usage.

**Secrets and tokens are heavily env-driven:**
- Risk: OpenAI, Langfuse, Letta, OpenMemory, telemetry, and service credentials all arrive through environment variables.
- Files: `.env.production.example`, `src/atelier/infra/internal_llm/openai_client.py`, `src/atelier/gateway/integrations/langfuse.py`, `src/atelier/infra/memory_bridges/letta_adapter.py`.
- Recommendation: keep examples sanitized and avoid checking live env files or generated docs with real values.

## Performance Bottlenecks

**Code-intel/indexing engine is a hotspot:**
- Problem: `src/atelier/core/capabilities/code_context/engine.py` is both huge and central to search/symbol/route/impact behavior.
- Likely impact: indexing/search performance and maintenance cost dominate a large slice of runtime complexity.
- Improvement path: continue splitting providers/caches/output policy into smaller units while preserving the external API.

**Service and MCP transports are monoliths:**
- Problem: `src/atelier/core/service/api.py` and `src/atelier/gateway/adapters/mcp_server.py` concentrate many unrelated routes/tools.
- Likely impact: slower iteration, larger import/test surfaces, and harder hot-path tuning.
- Improvement path: peel off feature-specific routers/tool handlers behind stable registries.

## Fragile Areas

**Host plugin hooks and install flows:**
- Why fragile: they modify user-host config, depend on external CLIs, and span multiple operating systems.
- Files: `scripts/install.sh`, `scripts/install_claude.sh`, `integrations/claude/plugin/hooks/`, `integrations/codex/hooks/`, `integrations/copilot-cli/hooks/`.
- Safe modification: verify with generated-surface tests and install/verify scripts before changing install logic.

**Swarm orchestration and worktree management:**
- Why fragile: it coordinates subprocesses, git worktrees, artifacts, and state transitions.
- Files: `src/atelier/core/capabilities/swarm/capability.py`, `src/atelier/infra/runtime/swarm_worktree.py`, `frontend/src/pages/Swarm.tsx`.
- Safe modification: add/keep targeted swarm tests before changing runner, evaluator, or patch-application logic.

## Scaling Limits

**Local-first storage defaults:**
- Current capacity: default runtime state is file-backed under `~/.atelier` with SQLite as the default backend.
- Limit: single-node/local usage is the happy path; scaling requires switching to PostgreSQL and more deliberate deployment wiring.
- Files: `src/atelier/core/foundation/paths.py`, `src/atelier/infra/storage/factory.py`, `.env.production.example`.

**Single-service / optional-frontend deployment model:**
- Current capacity: `docker-compose.yml` and `atelier stack` assume one service process plus one frontend process.
- Limit: no out-of-the-box multi-node orchestration or queue-backed worker architecture is present in the repo.

## Dependencies at Risk

**Many optional vendor integrations increase matrix complexity:**
- Risk: OpenAI-compatible, Ollama, Letta, OpenMemory, Langfuse, Postgres/vector, and host-specific CLIs all expand the support matrix.
- Files: `pyproject.toml`, `src/atelier/infra/internal_llm/`, `src/atelier/infra/memory_bridges/`, `src/atelier/gateway/hosts/configs/*.yaml`.
- Impact: dependency/API drift can break low-frequency integration paths.

## Missing Critical Features

**Imported-session trace persistence is incomplete:**
- Problem: imported session reconstruction still has TODOs instead of a finished trace-write path.
- Files: `src/atelier/core/service/ingest_session.py`, `src/atelier/core/service/ingest_session_directory.py`.
- Blocks: parity between imported-session analytics and native-session analytics.

**No browser-level end-to-end UI suite is obvious in the current stack:**
- Problem: frontend tests are page/component tests with mocked fetches, but no Playwright/Cypress-style browser runner is declared.
- Files: `frontend/package.json`, `frontend/src/pages/*.test.tsx`, `.github/workflows/tests.yml`.
- Blocks: full stack regressions between `frontend/` and `src/atelier/core/service/api.py` rely on manual smoke tests or narrower automation.

## Test Coverage Gaps

**Cross-surface install/host reality checks still depend on external environments:**
- What's not fully covered: every real host CLI + plugin environment combination.
- Files: `scripts/install.sh`, `integrations/*/install.sh`, `tests/gateway/test_agent_cli_install_artifacts.py`.
- Risk: generated artifacts can pass repository tests but still fail in a specific host/runtime environment.

**Large monolith surfaces are difficult to exhaustively cover:**
- What's not fully covered: every interaction path inside `engine.py`, `api.py`, and `mcp_server.py`.
- Files: `src/atelier/core/capabilities/code_context/engine.py`, `src/atelier/core/service/api.py`, `src/atelier/gateway/adapters/mcp_server.py`.
- Risk: localized edits can introduce regressions far from the edited branch.

---

*Concern analysis: 2026-06-02*
*Update after significant debt paydown, incident response, or architecture changes*
