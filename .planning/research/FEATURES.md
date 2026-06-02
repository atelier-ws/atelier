# Feature Research

**Domain:** Terminal-first agent runtime brownfield retrofit
**Researched:** 2026-06-02
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Durable context + session recall | Users expect the agent to remember repo/session state and not re-ask or re-read everything | MEDIUM | Already a current Atelier strength and must remain intact |
| Precise code-intel | Users expect symbol-aware answers, callers/usages/impact, not only text grep | HIGH | Existing Atelier differentiator; do not regress it into generic search |
| Search-first terminal UX | Users expect a cheap path for read/search/find operations without excessive tool churn | MEDIUM | WOZ-style ergonomics are the main missing UX simplifier |
| Editable terminal execution loop | Users expect explore -> plan -> execute flows to persist enough state to stay coherent | HIGH | This is where Eval is stronger today |
| Tracing / session accounting | Users expect visibility into what the system did and how much it cost | MEDIUM | Already partly present via ledger/report/telemetry |
| Real benchmark evidence | Claims about savings/quality need proof, not anecdotes | MEDIUM | This is the real verifier for this reset |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Routed subcall execution | Pick the right provider/model for owned subcalls instead of relying on one static path | HIGH | Current Atelier has advisory logic; milestone 1 should make it real on subcalls |
| Search-first + code-intel escalation | Low roundtrip default path without sacrificing deep semantic tooling | HIGH | Strong hybrid of WOZ ergonomics and Atelier strengths |
| Typed workflow kernel | Better plan/execute quality and lower prompt churn than prompt-only orchestration | HIGH | The most important Eval mechanism to borrow |
| Benchmark-backed savings UX | Make cost savings visible, but tie them to quality and repeatable evidence | MEDIUM | Better than raw counters alone |
| Host-side guardrails without host replacement | Improve behavior through hooks and nudges instead of full control takeover | MEDIUM | Lower risk than replacing the host conversation loop |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Clean-slate rewrite | Feels simpler than untangling a broad codebase | Throws away current strengths and resets proof/compatibility work | Brownfield extraction plus targeted retrofit |
| Full host override routing on day one | Feels like the purest routing story | Too risky before subcall routing proves itself in benchmarks | Start with Atelier-owned subcalls only |
| Web/dashboard-first expansion | Feels like visible product progress | Distracts from the actual terminal-first goal | Keep UI optional and secondary |
| "Project brain" positioning before proof | Sounds compelling | Creates vague scope and overclaims beyond the code | Ship workflow kernel + measurable context savings first |

## Feature Dependencies

```text
[Benchmark Gate]
    └──requires──> [Typed Workflow Kernel]
                       └──requires──> [Search-first Core Loop]

[Routed Subcall Execution]
    └──requires──> [Provider Execution Layer]
                       └──requires──> [Benchmark Gate]

[Savings UX] ──enhances──> [Benchmark Gate]

[Generic Search Replacement] ──conflicts──> [Precise Code-Intel]
```

### Dependency Notes

- **Benchmark Gate requires Workflow Kernel:** quality/cost claims are not meaningful if execution state is still too loose.
- **Workflow Kernel requires Search-first Core Loop:** the loop needs a cheap default path before it can demonstrate prompt-churn savings.
- **Routed Subcall Execution requires Provider Execution Layer:** current advisory routing is not enough.
- **Generic Search Replacement conflicts with Precise Code-Intel:** Atelier should compose its existing semantic tools, not flatten them away.

## MVP Definition

### Launch With (v1)

- [ ] Search-first default path with Edit/Recall/Sql ergonomics
- [ ] Typed workflow kernel with explicit plan review and task-local carry-forward state
- [ ] Routed provider execution for Atelier-owned subcalls
- [ ] Paired benchmark gate for non-inferior quality + lower spend
- [ ] Preserved Atelier strengths in memory, code-intel, and tracing

### Add After Validation (v1.x)

- [ ] Minified read/edit path — add once safe formatter/back-translation paths are proven
- [ ] Stronger savings/status UX — after benchmark truth is already in place
- [ ] Broader route shadowing and comparison — once subcall routing is stable

### Future Consideration (v2+)

- [ ] Top-level host routing enforcement — only after parity and trust are established
- [ ] Measured surface cuts across UI/API/SDK — only after parity review proves they are expendable
- [ ] Broader "project brain" positioning — only after persistent workflow/context mechanisms are demonstrably real

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Search-first default path | HIGH | MEDIUM | P1 |
| Typed workflow kernel | HIGH | HIGH | P1 |
| Routed subcall execution | HIGH | HIGH | P1 |
| Benchmark gate | HIGH | MEDIUM | P1 |
| Minified read/edit path | MEDIUM | HIGH | P2 |
| Expanded savings UX | MEDIUM | MEDIUM | P2 |
| Top-level host override routing | MEDIUM | HIGH | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | Eval | WOZ | Our Approach |
|---------|-----|-----|--------------|
| Workflow kernel | Strong explicit session/workflow machinery | Weak / not the focus | Borrow the kernel ideas into Atelier's brownfield runtime |
| Search/Edit ergonomics | Less decisive than WOZ | Strong default-path discipline | Compose WOZ-style ergonomics over Atelier's stronger internals |
| Provider routing | Not the main differentiator in inspected code | Installed local router exists, but host/plugin-oriented | Build Atelier-native subcall routing using existing advisory/ranking foundations |
| Code-intel | Good runtime mechanics, weaker inspected semantic UX than Atelier | More generic UX-first | Preserve Atelier's sharper semantic differentiation |

## Sources

- `.planning/PROJECT.md`
- `.planning/research/RESET-RESEARCH.md`
- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/INTEGRATIONS.md`

---
*Feature research for: terminal-first agent runtime brownfield retrofit*
*Researched: 2026-06-02*
