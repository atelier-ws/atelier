# Pitfalls Research

**Domain:** Terminal-first agent runtime brownfield retrofit
**Researched:** 2026-06-02
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: Rebuilding The Platform Instead Of Fixing The Core Loop

**What goes wrong:**
The work expands into broad UI/service/integration changes while the terminal execution path stays fragmented and expensive.

**Why it happens:**
Breadth feels like progress, and the repo already exposes many surfaces that are easy to keep touching.

**How to avoid:**
Anchor roadmap phases to the Search-first path, workflow kernel, routed subcalls, and benchmark gate before broadening scope.

**Warning signs:**
- New secondary surfaces appear before the default terminal path is measurably better
- Lots of refactors, little benchmark movement
- Planning language drifts back toward "platform" instead of "terminal-first core"

**Phase to address:**
Terminal core and early workflow-kernel phases

---

### Pitfall 2: Mistaking Advisory Routing For Real Routing

**What goes wrong:**
The system reports route recommendations, but actual provider execution still follows the host/default path.

**Why it happens:**
Current Atelier already has strong routing logic and telemetry, so it is easy to overcount that as finished routing behavior.

**How to avoid:**
Introduce an explicit provider execution layer for Atelier-owned subcalls and claim routing gains only where execution is truly owned.

**Warning signs:**
- Benchmarks show recommendations but not actual provider/model execution artifacts
- Product language says "routed" while code still labels behavior advisory/shadow/local-only

**Phase to address:**
Routing execution phase

---

### Pitfall 3: Benchmark Claims Without Paired Proof

**What goes wrong:**
Savings or quality claims rely on anecdotal sessions, counters, or unpaired runs.

**Why it happens:**
Savings UX is easier to ship than artifact-backed paired evaluation.

**How to avoid:**
Freeze a benchmark corpus, keep baseline conditions equal, run paired repeated evaluations, and require artifact-backed non-inferior quality plus lower spend.

**Warning signs:**
- Session counters are used as proof
- Baseline and treatment differ in model/provider/prompt conditions
- Off-topic or invalid runs are treated as wins

**Phase to address:**
Benchmark gate phase

---

### Pitfall 4: Replacing Code-Intel With Generic Search

**What goes wrong:**
The product becomes simpler, but loses one of Atelier's strongest actual advantages.

**Why it happens:**
WOZ-style ergonomics are attractive, and generic search feels cheaper to unify around.

**How to avoid:**
Make Search the default path, but keep semantic tools as a clear escalation path instead of deleting or hiding them.

**Warning signs:**
- Search answers become broader but less precise
- Symbol/call-graph tools stop being part of the intended loop

**Phase to address:**
Tool-surface consolidation phase

---

### Pitfall 5: Over-Verifying Tiny Steps Instead Of The Real Slice

**What goes wrong:**
Planning/execution slows down because small steps are repeatedly verified before the vertical slice is even coherent.

**Why it happens:**
Workflow quality controls are easier to add everywhere than to target at the true benchmark boundary.

**How to avoid:**
Use coarse implementation slices, keep extra per-step verification minimal, and rely on the end-to-end benchmark/phase gate as the main verifier.

**Warning signs:**
- High planning/check overhead before the feature loop is runnable
- Many "verified" intermediate states that still do not produce a working slice

**Phase to address:**
Planning and execution policy phases

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Keep adding logic to monolith files | Faster local edits | Bigger blast radius and harder extraction later | Only as a temporary bridge when a focused extraction immediately follows |
| Count advisory route simulations as shipping progress | Easier demos | False confidence and misleading claims | Never |
| Build savings UI before benchmark truth | Looks impressive quickly | Product drift toward unproven claims | Only if clearly labeled as non-proof telemetry |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Host hooks | Make them blocking too early | Start with soft nudges and measured guardrails |
| Provider routing | Override top-level host chat before subcalls are proven | Start with Atelier-owned execution lanes only |
| Optional memory/telemetry sidecars | Assume failures are visible by default | Keep diagnostics/reporting clear because many integrations fail open |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Prompt/state recomposition every step | High token churn and inconsistent execution context | Add typed workflow state and carry-forward outputs | Breaks immediately on multi-step tasks |
| Search/read roundtrip inflation | Too many calls for basic file discovery | Make Search-first composition the default | Breaks on benchmarked terminal tasks quickly |
| Broad route experimentation without execution ownership | Lots of route metadata but no measurable savings | Narrow routing scope to owned subcalls first | Breaks as soon as claims need proof |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Leaving service auth off outside local-only usage | Exposes powerful runtime endpoints | Treat auth as mandatory beyond loopback/local development |
| Environment-driven provider/router changes without clear ownership | Hidden routing behavior and hard-to-debug failures | Make route execution explicit and artifact-backed |
| Treating host/plugin routing rewrites as harmless defaults | Can silently change provider behavior | Keep router changes explicit, reviewable, and benchmarked |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Too many equally "primary" tools | Higher decision cost and more roundtrips | One Search-first default path with clear escalation |
| Cost-saving claims without quality context | Users distrust the product story | Tie savings UX to benchmark-backed proof |
| Broad workflow theory without visible execution discipline | Users feel the system is still loose and chatty | Ship explicit plan review, task state, and better execution coherence |

## "Looks Done But Isn't" Checklist

- [ ] **Routing:** Often missing real provider execution ownership — verify actual vendor/model execution artifacts exist
- [ ] **Workflow kernel:** Often missing durable task/output state — verify the next step can continue without re-deriving context
- [ ] **Search-first UX:** Often missing semantic escalation — verify code-intel paths are still first-class when needed
- [ ] **Benchmark proof:** Often missing paired repeat runs — verify quality and cost are compared under matched conditions
- [ ] **Savings UX:** Often missing proof boundary — verify counters are not presented as benchmark truth

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Platform breadth before core loop | HIGH | Freeze scope, define the terminal-first slice again, re-order roadmap around the core loop |
| Advisory routing mistaken for real routing | MEDIUM | Add explicit execution artifacts and narrow claims until enforcement is real |
| Generic search regression | MEDIUM | Reintroduce semantic escalation surfaces into the default flow |
| Weak benchmark proof | MEDIUM | Freeze corpus, re-run paired tests, and reset claims to match evidence |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Platform breadth before core loop | Terminal core phase | Default terminal path is measurably simpler and cheaper |
| Advisory routing mistaken for real routing | Routing execution phase | Actual provider/model execution is recorded for owned subcalls |
| Weak benchmark proof | Benchmark gate phase | Paired benchmark artifacts support the milestone claim |
| Search replacing code-intel | Tool-surface consolidation phase | Search-first path still escalates to semantic tooling when required |
| Over-verifying tiny steps | Planning policy phase | Coarse slices produce working end-to-end flows before benchmark review |

## Sources

- `.planning/research/RESET-RESEARCH.md`
- `.planning/PROJECT.md`
- `.planning/codebase/CONCERNS.md`
- `.planning/codebase/INTEGRATIONS.md`

---
*Pitfalls research for: terminal-first agent runtime brownfield retrofit*
*Researched: 2026-06-02*
