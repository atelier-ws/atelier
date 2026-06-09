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
Phases execute in numeric order: 1 → … → 9 → 10 → 11 → 12 → 13

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1-5. Owned Session Core → Reporting | ✓ | Complete | 2026-06-08 |
| 6. 4-Pane Layout + Expanded Protocol | ✓ | Complete | 2026-06-09 |
| 7. MCP Integration + Background Tasks | ✓ | Complete | 2026-06-09 |
| 8. Analytics + CI + Checkpoint | ✓ | Complete | 2026-06-09 |
| 9. Advanced Commands + Savings Panel | ✓ | Complete | 2026-06-09 |
| 10. Tab-Based Pane System | 0/TBD | Not started | - |
| 11. Provider Authentication Wizard | 0/TBD | Not started | - |
| 12. UX Polish: Tunnel + Selection + QR | 0/TBD | Not started | - |
| 13. Stem Agent + Shared Context Engine | 0/TBD | Not started | - |

---

### Phase 10: Tab-Based Pane System
**Goal**: Upgrade the 4-pane layout to a fully tabbed workspace — left tabs (Sessions/Files/Git), middle tabs (Conversation + closeable file/diff tabs), right-top tabs (Tools/Tasks/Subagents). File/diff clicks open new tabs. Both side panes are hideable.
**Depends on**: Phase 6
**Requirements**: Ratatui Tabs widget, ratatui-explorer file tree, similar crate for diff, side-by-side diff view, mouse/keyboard tab management
**Success Criteria**:
  1. Left pane has 3 tabs: Sessions (list), Files (ratatui-explorer tree), Git (git status)
  2. Middle pane has Conversation (permanent) + closeable File and Diff tabs opened by clicking files/git status
  3. Right top pane has Tools/Tasks/Subagents tabs; right bottom is Context/Route (30%)
  4. Pressing `[` / `]` hides/shows left and right panes respectively
  5. Side-by-side diff renders correctly for any modified file
**Plans**: TBD

### Phase 11: Provider Authentication Wizard
**Goal**: First-run interactive wizard that guides users through selecting a provider, entering credentials, validating them, and picking a default model. Saves to `~/.atelier/.env` for persistence.
**Depends on**: Phase 10
**Requirements**: Provider-specific auth forms (API key, base URL, service account, AWS profile), credential validation via litellm, model listing after auth, save to `~/.atelier/.env`
**Provider auth mechanisms**:
  - Anthropic: `ANTHROPIC_API_KEY` (console.anthropic.com)
  - OpenAI: `OPENAI_API_KEY` (platform.openai.com)
  - Google/Gemini: `GOOGLE_API_KEY` or `GEMINI_API_KEY` (ai.google.dev)
  - AWS Bedrock: `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_REGION_NAME` (or `AWS_PROFILE`)
  - GCP Vertex: `VERTEXAI_PROJECT` + `VERTEXAI_LOCATION` + `GOOGLE_APPLICATION_CREDENTIALS`
  - Azure OpenAI: `AZURE_API_KEY` + `AZURE_API_BASE` + `AZURE_API_VERSION`
  - OpenRouter: `OPENROUTER_API_KEY` (openrouter.ai)
  - Groq: `GROQ_API_KEY` (console.groq.com)
  - Mistral: `MISTRAL_API_KEY` (console.mistral.ai)
  - Ollama: `OLLAMA_HOST` (default http://localhost:11434, no key needed)
  - Together: `TOGETHER_API_KEY` (api.together.xyz)
  - Fireworks: `FIREWORKS_API_KEY` (fireworks.ai)
**Success Criteria**:
  1. On first run (no API keys), shows provider selection menu with all 12 providers
  2. Each provider shows exactly what credentials are needed with links
  3. Credentials are validated before saving (test API call)
  4. After auth, models are loaded from provider and shown in a picker
  5. Selected model + credentials saved to `~/.atelier/.env`

### Phase 12: UX Polish — Tunnel, Selection, QR Visibility
**Goal**: Fix tunnel URL visibility, cloudflared ToS issue, add text selection/copy, make web/QR visible inside TUI from the start.
**Depends on**: Phase 10
**Requirements**: arboard clipboard, mouse event handling for selection, cloudflared `--accept-tos`, pinned URL/QR banner in conversation
**Success Criteria**:
  1. Tunnel URL + QR code shown as pinned header at the TOP of the conversation pane (always visible, updates when tunnel connects)
  2. Cloudflared connects without pointing to ToS page (`--accept-tos` flag)
  3. Conversation text is selectable with mouse; Ctrl+C copies selection to clipboard
  4. Tunnel URL is clickable (OSC 8 hyperlink escape sequence where terminal supports it)

### Phase 13: Stem Agent + Shared Context Engine
**Goal**: One large generic system prompt shared across all modes/turns for maximum cache reuse. Role differentiation via minimal per-turn user messages, never via system prompt mutation.
**Depends on**: Phase 9
**Requirements**: New `StemAgentPrompt` class, stable immutable system prefix across entire session, role context injected as user message prefix
**Success Criteria**:
  1. System prompt is set once at session start and NEVER modified (even between modes)
  2. Mode/role context injected as `[MODE: explore]` prefix in user messages
  3. Cache hit rate measurably improves across multi-turn sessions (>70% target)
  4. New `STEM_PROMPT_VERSION` field in context stats pane

---

## Phase 6: 4-Pane Layout + Expanded Protocol
**Goal**: Upgrade the Ratatui TUI to a 4-pane fullscreen workspace (Sessions/Agents | Conversation | Context/Memory/Route | Tools/Diffs) with an expanded event protocol covering shell execution, context usage, memory hits, tasks, subagents, and checkpoints.
**Depends on**: Phase 5
**Requirements**: 4-pane layout, !shell mode, context usage pane, memory hits display, expanded BackendEvent protocol
**Success Criteria**:
  1. 4-pane layout with Sessions sidebar, Conversation, Context/Route/Savings pane, Tools/Diffs pane
  2. `!cmd` prefix in input executes shell commands and streams output into Tools pane
  3. Context usage pane shows token counts, cache efficiency, savings in real-time
  4. Memory hits appear in the Context pane when agent reads from Atelier memory
  5. Expanded event protocol emitted by Python backend (context.usage.updated, memory.hit, shell.*, task.*)
**Plans**: TBD

### Phase 7: MCP Integration + Background Tasks
**Goal**: Spawn and wire MCP servers from .mcp.json into the agent tool loop; add background task tracking so long-running operations don't block the TUI.
**Depends on**: Phase 6
**Requirements**: MCP server spawning, MCP tool exposure, /tasks command, background session support
**Success Criteria**:
  1. MCP servers from .mcp.json are auto-detected, spawned, and their tools are available to the agent
  2. /tasks shows a list of background tasks with live status
  3. Long-running tool calls can be backgrounded (! prefix or Ctrl+B)
  4. Subagent cards show in Sessions pane when spawned
**Plans**: TBD

### Phase 8: Analytics + CI + Checkpoint/Rewind
**Goal**: Persist session analytics to SQLite; add headless CI/JSON output mode; add checkpoint/rewind foundation.
**Depends on**: Phase 7
**Requirements**: SQLite analytics, `atelier run --json`, /checkpoint, /rewind, session collaboration
**Success Criteria**:
  1. `atelier run --json "<task>"` produces structured JSON output for CI pipelines
  2. SQLite stores per-session cost, cache efficiency, model, duration
  3. /checkpoint saves a snapshot; /rewind restores it
  4. Read-only session share link for collaboration
**Plans**: TBD

### Phase 9: Advanced Commands + Savings Panel
**Goal**: Complete the Claude Code feature parity with /plan, /btw, /usage, savings panel, Ctrl+R reverse search, and prompt suggestions.
**Depends on**: Phase 8
**Requirements**: /plan mode, /btw ephemeral questions, savings panel, Ctrl+R search, prompt suggestions
**Success Criteria**:
  1. /plan mode runs exploration-only with no edits
  2. /btw asks an ephemeral question without polluting conversation history
  3. Savings panel shows cache hits, VFS savings, routing savings vs naive baseline
  4. Ctrl+R opens reverse search over prompt history
  5. Prompt suggestions appear after warm-cache responses
**Plans**: TBD
