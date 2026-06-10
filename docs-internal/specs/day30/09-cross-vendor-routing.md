# Spec 09 — Cross-Vendor Live Routing

> Phase 2. The structural moat — natives cannot do this.

## Why

Today `ModelRouter` scores within one vendor (Claude haiku / sonnet / opus). Cross-vendor routing extends this so a single session can use Claude sonnet for edits, Gemini flash for reads, and GPT-4o for agent calls — whichever model is best per turn.

This is the feature **no native vendor will ship** because it routes their customer to a competitor on some turns.

## What — user-visible

```bash
# Configure
$ atelier route configure
Which vendors do you have API keys for?
[x] Anthropic Claude
[x] OpenAI
[x] Google Gemini
Saved: 3 vendors enabled.

# Use it
$ atelier route plan --tool Read --task "find the failing test"
Recommendation: gemini-flash
Reason: read tool, exploration phase (turn 2), bounded task
Estimated cost: $0.002 vs $0.01 on sonnet (saves 80%)

# In session — the MCP server intercepts and offers cross-vendor recommendations
# (transparent to the host CLI)
```

In Atelier-wrapped sessions, the model recommendation event includes cross-vendor tier:

```json
{
  "kind": "model_recommendation",
  "tier": "cheap",
  "model": "gemini-flash",
  "vendor": "google",
  "alternatives": [
    {"vendor": "anthropic", "model": "claude-haiku-4-5", "est_cost": 0.012},
    {"vendor": "openai",    "model": "gpt-4o-mini",      "est_cost": 0.008},
    {"vendor": "google",    "model": "gemini-flash",     "est_cost": 0.003}
  ],
  "reasons": [...]
}
```

## Where — files

| File | What changes |
|------|-------------|
| `src/atelier/core/capabilities/model_routing/router.py` | Extend `ModelRouter` with `enabled_vendors` and cross-vendor model selection |
| `src/atelier/core/capabilities/model_routing/vendor_catalog.py` | **New.** Vendor-model-capability mapping. |
| `src/atelier/core/capabilities/model_routing/cross_vendor_scorer.py` | **New.** Picks best model across vendors at a tier. |
| `src/atelier/gateway/adapters/cli.py` | Add `route configure`, `route plan` |
| `src/atelier/gateway/adapters/mcp_server.py` | Include `alternatives` in model_recommendation payload |
| `tests/core/capabilities/model_routing/test_cross_vendor.py` | **New.** |

## Vendor catalog

Static for v1 (audit-friendly). Updated quarterly with explicit changelog.

```python
VENDOR_CATALOG: dict[str, VendorModels] = {
    "anthropic": VendorModels(
        cheap="claude-haiku-4-5",
        medium="claude-sonnet-4.6",
        expensive="claude-opus-4-7",
        strengths={"code_editing", "long_context", "tool_use"},
    ),
    "openai": VendorModels(
        cheap="gpt-4o-mini",
        medium="gpt-4o",
        expensive="gpt-5",
        strengths={"code_editing", "function_calling", "math"},
    ),
    "google": VendorModels(
        cheap="gemini-flash",
        medium="gemini-pro",
        expensive=None,  # Google doesn't have a clear "opus tier"
        strengths={"long_context", "multimodal", "bulk_read"},
    ),
}
```

## Tier-to-model selection rule

Given scored tier and enabled vendors:

1. For each enabled vendor with a model at that tier:
2. Compute estimated cost for `(input_tokens, output_tokens)`
3. Apply quality-adjusted cost = cost × divergence_penalty (from replay data)
4. Pick lowest quality-adjusted cost
5. Tie-break: prefer the vendor with `cache_affinity_model` set

`divergence_penalty` per vendor-model pair is calibrated from replay data:
- haiku ↔ sonnet: 1.5 (78% divergence → significant retry risk)
- gemini-flash ↔ sonnet: 1.3 (calibrate from real replay)
- gpt-4o-mini ↔ sonnet: 1.4

Start with these defaults; outcome capture (spec 01) tunes them.

## Output token ratio adjustment

Cheaper models produce more output tokens (uncertainty hedging). Apply ratio when estimating cost:

```python
adjusted_output = expected_output_tokens × output_ratio[model]
est_cost = (input_tokens × input_price) + (adjusted_output × output_price)
```

## API key management

- Read from environment: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`
- If `atelier route configure` is run and a vendor isn't keyed, store the empty preference but log warning
- Never store API keys in Atelier config; environment only

## Out of scope

- **Actually invoking the cross-vendor models.** Atelier remains advisory — host CLI still picks. This spec adds cross-vendor recommendations; whether the host follows is its decision.
- **Streaming / unified protocol.** Each native CLI uses its own protocol.
- **Cost-based hard caps.** Future spec for "stop session if cost exceeds $X".

## Acceptance criteria

- [ ] `atelier route plan --tool X` returns a cross-vendor recommendation
- [ ] Recommendation payload includes `alternatives` array
- [ ] Disabled vendors are excluded from alternatives
- [ ] `route configure` writes preferences to `~/.atelier/route_config.yaml`
- [ ] Unit tests cover: single-vendor enabled, all-vendors enabled, no-vendors-enabled fallback
- [ ] Cross-vendor benchmark added (`benchmark cross-vendor-savings`)
- [ ] Updated benchmark publication (spec 05) includes cross-vendor numbers

## Open questions

1. **Quality calibration.** Do we have replay data for OpenAI and Gemini yet? **Default: bootstrap with conservative defaults (penalty 1.4 across the board), refine via spec 01 outcome capture.**
2. **Capability gating.** If a turn needs vision, only certain vendors qualify. **Default: filter by `strengths` set before scoring.**
3. **Should we expose cross-vendor recommendations to non-Atelier-wrapped sessions?** **Default: no, only sessions running through Atelier MCP server.**

## Status

- [ ] Pending
- [ ] In progress
- [ ] Shipped
