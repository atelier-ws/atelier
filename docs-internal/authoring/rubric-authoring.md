# Rubric Authoring

Rubrics define the explicit checks Atelier evaluates before accepting a result.
They are YAML documents validated against the `Rubric` model in
`src/atelier/core/foundation/models.py`.

## Current File Format

Rubrics load from `src/atelier/core/rubrics/` (via `load_packaged_rubrics()`);
no seed rubrics ship there today. A rubric looks like this:

```yaml
id: rubric_state_change_safety
domain: state.change
required_checks:
  - canonical_identifier_used
  - pre_change_state_captured
  - read_after_write_completed
  - observed_state_matches_intent
block_if_missing:
  - canonical_identifier_used
  - read_after_write_completed
  - observed_state_matches_intent
warning_checks:
  - rollback_plan_available
  - user_visible_surface_checked
escalation_conditions:
  - target_identity_ambiguous
  - live_system_drift_detected
  - rollback_failed
related_blocks:
  - canonical-identifier-over-display-name
  - read-after-write-verification
```

## Field Guide

- Required: `id`, `domain`
- Optional routing hints: `triggers`, `related_blocks`
- Optional content filters: `forbidden_phrases`
- Gate definitions: `required_checks`, `block_if_missing`, `warning_checks`, `escalation_conditions`

## Current Contributor Workflow

1. Add or edit a YAML file under `src/atelier/core/rubrics/`.
1. Validate a clean import:

```bash
ATELIER_ROOT=/tmp/atelier-docs-check uv run atelier init
```

1. Add targeted tests when the rubric changes a safety-critical contract.

## Important Note

Older docs referred to `atelier pack create/install` for rubrics and to an
`atelier verify <rubric-id>` CLI. Both have been removed; rubric gates run
inside the runtime.
