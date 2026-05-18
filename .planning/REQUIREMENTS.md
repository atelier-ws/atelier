# Requirements: Atelier Code Intelligence

**Defined:** 2026-05-18
**Core Value:** Agents can find and change code through budget-aware, precomputed intelligence with near-zero token overhead by default.

## v1 Requirements

### Foundation

- [ ] **FNDN-01**: Agent receives cached, budget-packed responses on existing `code` operations with `cache_hit`, `tokens_saved`, and `provenance` metadata.
- [ ] **FNDN-02**: Agent can query symbol intelligence through routed precomputed backends behind the existing `code` surface, starting with SCIP when an index is available.

### Navigation

- [ ] **NAVG-01**: Agent can search symbols with hardened defaults for snippets, ranking, and provenance on the existing `code op="search"` path.
- [ ] **NAVG-02**: Agent can find usages of a symbol through `code op="usages"` without falling back to ad hoc text search by default.
- [ ] **NAVG-03**: Agent can inspect callers and callees for a symbol through `code op="callers"` and `code op="callees"`.
- [ ] **NAVG-04**: Agent can search and resolve code intelligence across supported multi-repo workspaces with repo-aware results.

### Editing & Discovery

- [ ] **DISC-01**: Agent can apply symbol-scoped edits through the existing `edit` tool using a rich `kind="symbol"` descriptor.
- [ ] **DISC-02**: Agent can run structural code search through `code op="pattern"` with tree-sitter-aware matching instead of regex-only search.
- [ ] **DISC-03**: Agent can fall back to semantic symbol search over function-level embeddings when name-first retrieval is insufficient.
- [ ] **DISC-04**: Agent can recall symbol-linked memory through the existing memory/code surfaces to recover prior context with low token overhead.
- [ ] **DISC-05**: Agent can distinguish external dependency symbols from workspace symbols in code search results.

### History & Scale

- [ ] **HIST-01**: Agent can search deleted or renamed symbols and filter historical results by time window or author.
- [ ] **HIST-02**: Agent can inspect blame and churn metadata for a symbol to judge ownership and stability before editing.
- [ ] **SCAL-01**: Agent can route large-repo search workloads through a validated scale backend once the build-vs-integrate checkpoint clears it.
- [ ] **SCAL-02**: Agent can surface supported cross-language reference edges with confidence scoring for the planned Python/C, subprocess, and dynamic-import cases.

### Enablement

- [ ] **ENBL-01**: Agent gets first-context bootstrap and prefetch behavior that warms the most relevant code-intel state before the first retrieval-heavy task.
- [ ] **ENBL-02**: Maintainers have code-intel documentation, validation guidance, and scorecard metrics that explain when to use `code`, `read`, `search`, and symbol edits.
- [ ] **ENBL-03**: Maintainers have a documented build-vs-integrate decision record before large-repo backend work proceeds.

## v2 Requirements

### Deferred

- **DEFR-01**: Agent can resolve broader cross-language/runtime edges beyond the planned static subset (for example JNI, Rust FFI, or runtime-traced references).
- **DEFR-02**: Agent can query build-system dependency graphs as first-class code-intel edges for ecosystems like Bazel or Buck.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Serena or live LSP-per-session as the primary path | The grounded plan explicitly prefers precomputed artifacts over live session servers. |
| Replacing Atelier's `search` tool for text/regex cases | Text search remains the complement when symbol-first retrieval is not the right tool. |
| IDE plugins or new non-MCP delivery surfaces | The program stays within Atelier's existing runtime and host integrations. |
| Full cross-language/runtime coverage | The active plan only commits to the highest-value static edges. |
| Megarepo infrastructure beyond the Zoekt-scale target | The current program stops at the large-repo tier described in the active plan. |

## Traceability

Roadmap mapping will be filled in during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FNDN-01 | TBC | Pending |
| FNDN-02 | TBC | Pending |
| NAVG-01 | TBC | Pending |
| NAVG-02 | TBC | Pending |
| NAVG-03 | TBC | Pending |
| NAVG-04 | TBC | Pending |
| DISC-01 | TBC | Pending |
| DISC-02 | TBC | Pending |
| DISC-03 | TBC | Pending |
| DISC-04 | TBC | Pending |
| DISC-05 | TBC | Pending |
| HIST-01 | TBC | Pending |
| HIST-02 | TBC | Pending |
| SCAL-01 | TBC | Pending |
| SCAL-02 | TBC | Pending |
| ENBL-01 | TBC | Pending |
| ENBL-02 | TBC | Pending |
| ENBL-03 | TBC | Pending |

**Coverage:**
- v1 requirements: 18 total
- Mapped to phases: 0
- Unmapped: 18 ⚠

---
*Requirements defined: 2026-05-18*
*Last updated: 2026-05-18 after initial definition*
