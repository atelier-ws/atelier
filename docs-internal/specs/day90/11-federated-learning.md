# Spec 11 — Federated Outcome Learning (Outline)

> Phase 3. The deepest moat. Outline only — refine before execution.

## Why

Per-user outcome capture (spec 01) makes individual routing smarter over time. **Federated** outcome learning — anonymised across opt-in users — makes routing smarter for everyone, faster than any single user could achieve.

This is something no single-vendor native CLI can match: they can't aggregate across competitors' usage.

## What — user-visible

```bash
$ atelier federation opt-in
You're about to share anonymised outcome data with the Atelier federation.

We share:
  - Outcome scores by (tool, model, session_phase) bucket
  - Aggregate route divergence rates by vendor

We never share:
  - File paths, file contents, prompts
  - User identifiers, API keys
  - Specific tool inputs or outputs

Continue? (y/n) y
Federation enabled. Your routing benefits from ~12,400 other users' outcomes.

$ atelier federation status
Opt-in:           yes
Last upload:      2 hours ago (138 outcomes)
Last download:    2 hours ago
Routing benefit:  +4.2% accuracy on cross-vendor decisions
```

## Where — outline

- `src/atelier/core/capabilities/federation/` new package
- Server-side: separate atelier-federation repo (out of monorepo scope)
- Outcome aggregation: bucket by `(tool, vendor, model, session_phase, tier)` → EMA of outcome_score
- Distribution: signed multiplier deltas, applied client-side

## Privacy model

- Differential privacy noise added before upload
- Bucketed aggregates only — never per-session data
- Opt-in, off by default, easy to disable
- Open-source the aggregation algorithm

## Out of scope (for now)

- **Selling federated insights as a service.** Not a revenue lever.
- **Sharing across teams.** Spec 12 handles intra-team sharing.

## Open questions to resolve before executing

1. Differential privacy budget — what ε is acceptable?
2. Server-side infrastructure — Cloud Run? Fly.io? Self-host?
3. Anti-poisoning — how do we detect malicious clients sending fake outcomes?

## Status

- [ ] Outline — refine before execution
