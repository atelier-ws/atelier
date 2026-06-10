# Requirements: Atelier Owned Agent CLI

**Defined:** 2026-06-08
**Core Value:** Phase-linear warm-prefix reuse — Plan reads Survey's codebase context as a cache hit, not a cold re-read

## v1 Requirements

### Session Core

- [ ] **SESS-01**: User can run `atelier run "<task>"` to start an owned coding session on their own API credentials
- [ ] **SESS-02**: Session routes to provider/model via `select_owned_route` with `--provider`, `--model`, or `--budget cheap|balanced|best`
- [ ] **SESS-03**: Session executes Survey→Plan→Implement as a single phase-linear conversation using a generic stem-agent system prompt
- [ ] **SESS-04**: Phase differentiation done via injected user messages (not system prompt changes) so prefix stays byte-stable
- [ ] **SESS-05**: Session persists as JSONL under `~/.atelier/runs/<session-id>.jsonl`
- [ ] **SESS-06**: User can resume a session with warm prefix via `atelier run resume <session-id>`

### Cache Control

- [ ] **CACHE-01**: Stable system prefix is fixed at session start and never mutated mid-run; all per-phase intent goes in user turns
- [ ] **CACHE-02**: Explicit `cache_control` ephemeral breakpoint placed after stable prefix (system + tools + pinned context)
- [ ] **CACHE-03**: Cache affinity preserved — subsequent owned calls stay on the provider whose prefix is warm (`cache_affinity_for_route`)
- [ ] **CACHE-04**: `--cache-policy inherit|fresh` flag supported (default `inherit`)
- [ ] **CACHE-05**: `--phase-linear/--no-phase-linear` flag supported (default on)
- [ ] **CACHE-06**: Background keepalive pings every 5 min when session is idle to prevent 5-min TTL expiry
- [ ] **CACHE-07**: Within-session read dedup via existing `context_dedup` capability

### Minified Reads

- [ ] **READ-01**: Survey and Plan phases use whitespace-minified file reads (outline/compact projection via existing `atelier_read` outline mode)
- [ ] **READ-02**: Implement/edit phase uses exact byte-for-byte file reads

### Credentials & Safety

- [ ] **CRED-01**: Credentials discovered from env / `.env` via `detect_api_key_vendors`; CLI exits with actionable message when no key configured
- [ ] **CRED-02**: `--max-cost <usd>` flag aborts session if cost projection exceeds limit
- [ ] **CRED-03**: `--yolo` flag skips edit approval prompts; default is to confirm destructive edits
- [ ] **CRED-04**: `--dry-run` flag shows plan without executing edits

### Reporting

- [ ] **RPT-01**: Per-run receipt shown at session end: cache-read tokens, cache-write tokens, fresh-input tokens, cache efficiency %, $ spent
- [ ] **RPT-02**: $ vs naive (no-cache, per-phase-cold) baseline shown on receipt
- [ ] **RPT-03**: `atelier run report <session-id>` command to retrieve receipt for a past session
- [ ] **RPT-04**: Cache hit ratio reported (target: >60% cache efficiency)

## v2 Requirements

### Transport

- **TRANS-01**: `--transport anthropic-direct` for pure-Claude users wanting 1-hour TTL
- **TRANS-02**: `--ttl 1h` flag for headless/batch runs
- **TRANS-03**: Multi-provider mid-session cost-vs-cache warning when provider switch would evict warm prefix

### TUI

- **TUI-01**: Rich terminal UI
- **TUI-02**: Real-time token cost display during session

### Session Management

- **SES2-01**: SQLite session state for richer `resume` and `report` queries
- **SES2-02**: `atelier run list` to show past sessions with cost summaries
- **SES2-03**: `atelier run diff <session-id>` to show files changed in a session

### Compaction

- **COMP-01**: Cache-safe compaction (prefix-preserving fork, agentcache PPF algorithm) when conversation prefix itself becomes the cost
- **COMP-02**: `--max-context-ratio <0-1>` to control compaction trigger threshold

## Out of Scope

| Feature | Reason |
|---------|--------|
| Atelier-hosted inference / key brokering | Security non-goal; strictly user's own creds |
| Replacing host-CLI path | Claude Code/Codex users unaffected |
| New/better models | Quality tracks underlying model exactly |
| SQLite session state (v1) | JSONL sufficient; defer migration cost |
| `--transport anthropic-direct` (v1) | litellm covers Anthropic; 1-hour TTL is v2+ |
| Two-model Coordinator (DeepSeek-Reasonix pattern) | Premature; v1 uses single model per session |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SESS-01 | Phase 1 | Pending |
| SESS-02 | Phase 1 | Pending |
| SESS-03 | Phase 2 | Pending |
| SESS-04 | Phase 2 | Pending |
| SESS-05 | Phase 1 | Pending |
| SESS-06 | Phase 4 | Pending |
| CACHE-01 | Phase 2 | Pending |
| CACHE-02 | Phase 2 | Pending |
| CACHE-03 | Phase 2 | Pending |
| CACHE-04 | Phase 1 | Pending |
| CACHE-05 | Phase 2 | Pending |
| CACHE-06 | Phase 4 | Pending |
| CACHE-07 | Phase 3 | Pending |
| READ-01 | Phase 3 | Pending |
| READ-02 | Phase 3 | Pending |
| CRED-01 | Phase 1 | Pending |
| CRED-02 | Phase 4 | Pending |
| CRED-03 | Phase 1 | Pending |
| CRED-04 | Phase 1 | Pending |
| RPT-01 | Phase 5 | Pending |
| RPT-02 | Phase 5 | Pending |
| RPT-03 | Phase 5 | Pending |
| RPT-04 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 23 total
- Mapped to phases: 23
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-08*
*Last updated: 2026-06-08 after initial definition*
