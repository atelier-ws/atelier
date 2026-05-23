# Requirements: Atelier

**Defined:** 2026-05-23
**Core Value:** Atelier should deliver high-recall engineering context with strict token discipline and low latency.

## v1 Requirements

### Indexed File Discovery

- [ ] **FILES-01**: `code op="files"` returns indexed repository files with `tree`, `flat`, and `grouped` output formats
- [ ] **FILES-02**: `code op="files"` supports `path`, `pattern`, `include_metadata`, and `max_depth` filters without filesystem scans
- [ ] **FILES-03**: `code op="files"` response includes deterministic metadata (`repo_id`, `file_count`, `truncated`, `cache_hit`, `tokens_saved`, `provenance`)

### Explore Context Pack

- [ ] **EXPL-01**: `code op="explore"` returns grouped source snippets for related symbols in one response
- [ ] **EXPL-02**: `code op="explore"` includes relationship context (callers/callees/usages or equivalent links) with bounded counts
- [ ] **EXPL-03**: `code op="explore"` remains budget-safe under `budget_tokens` with deterministic truncation behavior

### Index Health and Freshness

- [ ] **STAT-01**: `code op="status"` reports index health, file/node/edge counts, and backend metadata
- [ ] **STAT-02**: `code op="status"` exposes cache and freshness hints suitable for agent routing decisions
- [ ] **STAT-03**: `code op="status"` response stays compact and host-neutral for MCP consumers

### Benchmarks and Documentation

- [ ] **DOCS-01**: `docs/sdk/mcp.md` documents all active `code` ops including `files`, `explore`, and `status` when shipped
- [ ] **BMRK-01**: Benchmarks report comparable token and latency outcomes for Atelier versus Serena and CodeGraph-style alternatives
- [ ] **BMRK-02**: Benchmark reporting keeps effective-token accounting visible for quality-adjusted comparisons

## v2 Requirements

### Deferred Enhancements

- **ROUT-01**: Add `code op="routes"` for framework route-node extraction
- **SYNC-01**: Add watcher/autosync for index freshness updates between manual indexing operations

## Out of Scope

| Feature | Reason |
|---------|--------|
| New top-level MCP tools | v2 parity is explicitly scoped to extending `mcp__atelier__code` |
| SCIP expansion work | Not required for files/explore/status milestone outcomes |
| Broad retrieval architecture rewrite | Incremental extension is lower-risk and reviewable in one PR |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| FILES-01 | Phase 6 | Pending |
| FILES-02 | Phase 6 | Pending |
| FILES-03 | Phase 6 | Pending |
| EXPL-01 | Phase 7 | Pending |
| EXPL-02 | Phase 7 | Pending |
| EXPL-03 | Phase 7 | Pending |
| STAT-01 | Phase 8 | Pending |
| STAT-02 | Phase 8 | Pending |
| STAT-03 | Phase 8 | Pending |
| DOCS-01 | Phase 9 | Pending |
| BMRK-01 | Phase 9 | Pending |
| BMRK-02 | Phase 9 | Pending |

**Coverage:**
- v1 requirements: 12 total
- Mapped to phases: 12
- Unmapped: 0

---
*Requirements defined: 2026-05-23*
*Last updated: 2026-05-23 after milestone v1.1 requirement definition*
