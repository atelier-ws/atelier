# Spec 07 — Counterfactual Per-Session Report

> Phase 2. The "shock the user with vendor comparison" feature.

## Why

Per-session reports (spec 02) show what was spent. Counterfactual reports show **what each alternative vendor would have cost**. This is the single most viral feature on offer — every developer wants to know "could I have saved money by using a different model for some turns?"

## What — user-visible

```bash
$ atelier session counterfactual 7c2f8a
Session 7c2f8a · 4h 12m · 92 turns
Actual: $7.45 on Anthropic Claude Sonnet 4.6
─────────────────────────────────────────────────

What each vendor would have cost
  Anthropic Claude (haiku)        $1.20    -$6.25  (-84%)
  Anthropic Claude (sonnet)       $7.45     $0.00       
  Anthropic Claude (opus)        $24.10   +$16.65 (+224%)
  OpenAI GPT-4o-mini              $0.85    -$6.60  (-89%)
  OpenAI GPT-4o                   $5.60    -$1.85  (-25%)
  Google Gemini Flash             $0.40    -$7.05  (-95%)
  Google Gemini Pro               $4.20    -$3.25  (-44%)

Smart routing — Atelier's recommendation
  Mix:   Sonnet for 64 edit/agent turns
         Gemini Flash for 28 read/grep turns
  Cost:  $4.10    saved $3.35 (-45%)
  Risk:  Low (read turns are exploration, cheap models fit)

Caveats
  Quality assumption: each model would have produced equivalent output.
  Real divergence rate (haiku vs sonnet replay): 78% — see methodology.
  Cross-vendor divergence is unknown without replay against each vendor.
```

## Where — files

| File | What changes |
|------|-------------|
| `src/atelier/infra/runtime/counterfactual.py` | **New module.** |
| `src/atelier/gateway/adapters/cli.py` | Add `session counterfactual` subcommand |
| `src/atelier/core/capabilities/pricing.py` | Extend with cross-vendor pricing table |
| `tests/infra/runtime/test_counterfactual.py` | **New tests.** |

## Pricing table

Hardcoded for v1 (deterministic, auditable). Updated quarterly.

```python
VENDOR_PRICING: dict[str, dict[str, ModelPricing]] = {
    "anthropic": {
        "claude-haiku-4-5":     ModelPricing(input=0.80, output=4.00),
        "claude-sonnet-4.6":    ModelPricing(input=3.00, output=15.00),
        "claude-opus-4-7":      ModelPricing(input=15.00, output=75.00),
    },
    "openai": {
        "gpt-4o-mini":          ModelPricing(input=0.15, output=0.60),
        "gpt-4o":               ModelPricing(input=2.50, output=10.00),
        "gpt-5":                ModelPricing(input=10.00, output=30.00),
    },
    "google": {
        "gemini-flash":         ModelPricing(input=0.075, output=0.30),
        "gemini-pro":           ModelPricing(input=1.25, output=5.00),
    },
}
```

## Counterfactual algorithm

For each session:

1. Walk all turns from the ledger
2. For each turn, get `(input_tokens, output_tokens, tool_name, session_phase)`
3. For each vendor × model combination:
   - Apply that vendor's haiku-equivalent output-token-ratio adjustment (haiku produces 1.88× more output, gemini-flash ~1.7×, etc.)
   - Compute total cost
4. Run Atelier's `ModelRouter` for the smart mix:
   - For each turn, get recommended tier
   - Map tier to best vendor-model at that tier (cheap = gemini-flash, medium = sonnet, expensive = opus)
   - Sum smart-routed cost

## Output-token-ratio adjustments

From replay benchmark data:

| Model | Output multiplier vs sonnet |
|-------|----------------------------|
| haiku | 1.88 |
| gpt-4o-mini | 1.65 |
| gemini-flash | 1.70 |
| gpt-4o | 1.10 |
| gemini-pro | 1.15 |

These are tuned over time from real replay data. Initial values from spec 05's replay results.

## Out of scope

- **Real counterfactual replay** against GPT and Gemini (expensive, slow). v2 spec.
- **Per-tool quality risk per vendor.** v2.
- **Charts.** Web dashboard.

## Acceptance criteria

- [ ] `atelier session counterfactual <id>` runs in <1s for a 100-turn session
- [ ] All vendor-model totals match (within $0.01) the manual calc against pricing table
- [ ] Output adjustment multipliers applied correctly
- [ ] "Smart routing" recommendation matches what `ModelRouter` would have done
- [ ] Caveats section always rendered
- [ ] `--json` flag works
- [ ] Unit tests with synthetic ledger cover all branches

## Open questions

1. Should we save the counterfactual results to disk? **Default: cache in session_state.counterfactual; recompute if pricing table changes.**
2. Should the caveats vary based on vendor confidence? **Default: same caveats every time for v1 — keeps the trust signal consistent.**

## Status

- [ ] Pending
- [ ] In progress
- [ ] Shipped
