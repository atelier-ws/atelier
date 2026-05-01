---
name: atelier-check-plan
description: Use when you have a concrete plan and want to verify it does not hit known dead ends before editing code. Required before any edit in beseam.shopify.publish, beseam.pdp.schema, beseam.catalog.fix, beseam.tracker.classification.
---

# Atelier Plan Check

This skill validates a proposed plan against the Atelier reasoning store.

## Required inputs

- `task` — one-sentence description of what you intend to do.
- `plan` — list of 3–8 imperative steps.

If either is missing, **ask the user for it**. Do not invent a plan.

Optional: `domain`, `files`, `tools`.

## Action

Call exactly:

```
atelier_check_plan({
  task,
  domain,
  plan,
  files,
  tools
})
```

## Interpret the result

- `status == "blocked"` → list the matched dead-end blocks and the
  `suggested_plan`. Tell the user: "I cannot proceed with the original
  plan. Here is the corrected plan from Atelier." Then call
  `atelier_check_plan` again on the corrected plan.
- `status == "warn"` → enumerate warnings, propose mitigations.
- `status == "ok"` → confirm and proceed.

## Hard rules

- Do not edit any file before this skill returns `ok`.
- Do not silently downgrade a `blocked` verdict.
