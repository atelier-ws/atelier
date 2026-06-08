# Roadmap: Atelier Owned Agent CLI

## Overview

This roadmap delivers `atelier run` — a user-owned coding-agent CLI built for maximum cache control. The journey starts with a single-shot owned session (route → execute → receipt) on the user's own API credentials, then grows the phase-linear Survey→Plan→Implement conversation that is the project's core value: the Plan phase reads Survey's ingested codebase context as a cheap cache hit instead of a cold re-read. From there we add minified reads and within-session dedup to shrink the warm prefix, harden the CLI with resume / keepalive / cost guardrails, and close with cache-economics reporting that proves the savings against a naive baseline. Each phase maps directly to a milestone (M1–M5) from `docs/plans/owned-agent-cli.md` and builds on existing owned-execution, cache-affinity, and dedup infrastructure rather than reinventing it.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [ ] **Phase 1: Owned Session Core** - Single-shot `atelier run "<task>"` owned session: route → execute → receipt with a stable prefix and one cache breakpoint
- [ ] **Phase 2: Phase-Linear Stem Agent** - Survey→Plan→Implement in one byte-stable conversation so Plan reads Survey's context as a cache hit
- [ ] **Phase 3: Minified Reads + Dedup** - Whitespace-minified reads on Survey/Plan, exact bytes on Implement, plus within-session read dedup
- [ ] **Phase 4: CLI Hardening** - Session resume with warm prefix, background keepalive pings, and cost guardrails
- [ ] **Phase 5: Reporting** - Per-run cache-economics receipt: cache-hit ratio and $ saved vs naive baseline

## Phase Details

### Phase 1: Owned Session Core
**Goal**: User can run a single-shot owned coding session on their own credentials that routes to a provider, executes, and persists as a replayable JSONL run with a stable cache-friendly prefix.
**Depends on**: Nothing (first phase)
**Requirements**: SESS-01, SESS-02, SESS-05, CACHE-04, CRED-01, CRED-03, CRED-04
**Success Criteria** (what must be TRUE):
  1. User can run `atelier run "<task>"` and get a completed owned session using their own API key, with provider/model selectable via `--provider`, `--model`, or `--budget cheap|balanced|best`.
  2. When no API key is configured, the CLI exits with an actionable message naming which env vars / `.env` vendors to set.
  3. User can run `--dry-run` to preview the plan without edits, and `--yolo` to skip edit-approval prompts (default confirms destructive edits).
  4. Each run persists to `~/.atelier/runs/<session-id>.jsonl` with a fixed stable prefix and one `cache_control` breakpoint, controllable via `--cache-policy inherit|fresh`.
**Plans**: TBD

### Phase 2: Phase-Linear Stem Agent
**Goal**: User gets a single byte-stable Survey→Plan→Implement conversation where the Plan phase reads Survey's ingested context as a cache hit rather than a cold re-read — the project's core savings lever.
**Depends on**: Phase 1
**Requirements**: SESS-03, SESS-04, CACHE-01, CACHE-02, CACHE-03, CACHE-05
**Success Criteria** (what must be TRUE):
  1. A single `atelier run` executes Survey→Plan→Implement as one conversation using a generic stem-agent system prompt, with phase intent injected via user turns (not system-prompt mutation).
  2. The stable system prefix is fixed at session start and never mutated mid-run; the `cache_control` ephemeral breakpoint sits after the stable prefix (system + tools + pinned context).
  3. Cache reporting shows the Plan phase reading Survey's context as cache-read tokens (a warm-prefix hit), and subsequent calls stay on the provider whose prefix is warm.
  4. User can toggle `--phase-linear/--no-phase-linear` (default on) to compare phase-linear vs per-phase-cold behavior.
**Plans**: TBD

### Phase 3: Minified Reads + Dedup
**Goal**: User's Survey/Plan phases read files in compact/minified form while Implement uses exact bytes, and repeated reads within a session are deduplicated — shrinking the warm prefix without losing edit fidelity.
**Depends on**: Phase 2
**Requirements**: CACHE-07, READ-01, READ-02
**Success Criteria** (what must be TRUE):
  1. During Survey and Plan, file reads come back whitespace-minified (outline/compact projection via existing `atelier_read` outline mode).
  2. During Implement/edit, file reads are exact byte-for-byte so edits apply cleanly.
  3. Re-reading the same file within a session is served from `context_dedup` rather than re-ingested, visible as reduced fresh-input tokens in the receipt.
**Plans**: TBD

### Phase 4: CLI Hardening
**Goal**: User can resume a session with its warm prefix intact, long idle sessions stay cached, and runs respect a cost ceiling.
**Depends on**: Phase 3
**Requirements**: SESS-06, CACHE-06, CRED-02
**Success Criteria** (what must be TRUE):
  1. User can run `atelier run resume <session-id>` to continue a session and observe cache-read hits against the still-warm prefix.
  2. While a session sits idle, background keepalive pings fire every 5 min so the 5-min cache TTL does not expire before resume.
  3. `--max-cost <usd>` aborts the session when the projected cost exceeds the limit, before incurring it.
**Plans**: TBD

### Phase 5: Reporting
**Goal**: User can see, at session end and on demand, exactly how much the cache control saved versus a naive no-cache baseline.
**Depends on**: Phase 4
**Requirements**: RPT-01, RPT-02, RPT-03, RPT-04
**Success Criteria** (what must be TRUE):
  1. At session end the receipt shows cache-read tokens, cache-write tokens, fresh-input tokens, cache efficiency %, and $ spent.
  2. The receipt shows $ spent vs a naive (no-cache, per-phase-cold) baseline so the savings are explicit.
  3. User can run `atelier run report <session-id>` to retrieve the receipt for any past session.
  4. The receipt reports the cache-hit ratio and compares it against Eval's 60–80% target.
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Owned Session Core | 0/TBD | Not started | - |
| 2. Phase-Linear Stem Agent | 0/TBD | Not started | - |
| 3. Minified Reads + Dedup | 0/TBD | Not started | - |
| 4. CLI Hardening | 0/TBD | Not started | - |
| 5. Reporting | 0/TBD | Not started | - |
