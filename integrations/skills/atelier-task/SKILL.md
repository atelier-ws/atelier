---
name: atelier-task
description: Use this skill at the start of every coding task — bug fixes, refactors, feature work, Beseam product agent changes, anything touching shopify/**, pdp/**, catalog/**, tracker/**, publish/**, schema/**, or backend services. It runs the full Atelier reasoning loop so you do not propose plans that hit known dead ends.
---

# Atelier Task Loop

When this skill activates, follow the loop **in order**. Do not skip steps.

## 1. Retrieve reasoning context

Call the MCP tool:

```
atelier_get_reasoning_context({
  task: "<one-sentence task>",
  domain: "<beseam.shopify.publish | beseam.pdp.schema | ... | null>",
  files: ["<likely files>"],
  errors: ["<known error messages>"]
})
```

Read every returned ReasonBlock. They are short on purpose.

## 2. Draft a plan

3–8 imperative steps. Reference the matched ReasonBlocks where relevant.

## 3. Validate the plan

```
atelier_check_plan({
  task: "<same task>",
  domain: "<same domain>",
  plan: ["step 1", "step 2", "..."],
  files: [...],
  tools: [...]
})
```

- `status == "blocked"` → **stop. Do not edit code.** Replace your plan
  with the response's `suggested_plan` and call `atelier_check_plan`
  again.
- `status == "warn"` → address every warning in the next revision.
- `status == "ok"` → proceed.

## 4. Implement

Make the smallest possible diff that satisfies the validated plan.

## 5. Rescue repeated failures

If the same test/command fails twice with the same error signature:

```
atelier_rescue_failure({
  task, error, files,
  recent_actions: ["last 3 actions"]
})
```

Apply the rescue **before** running the failing thing again.

## 6. Rubric gate (high-risk domains only)

For `beseam.shopify.publish`, `beseam.pdp.schema`, `beseam.catalog.fix`,
`beseam.tracker.classification` call `atelier_run_rubric_gate` with the
domain's `rubric_id` and a complete `checks` object.

## 7. Record trace

```
atelier_record_trace({
  agent: "atelier:code",
  domain, task, status,
  files_touched, tools_called, commands_run, errors_seen,
  diff_summary, output_summary, validation_results
})
```

Never include secrets, API keys, tokens, or hidden chain-of-thought.

## Hard rules

- Do not ignore `high`-severity Atelier warnings.
- Do not bypass `atelier_check_plan` by editing first.
- Do not invent plan steps that contradict matched ReasonBlocks.
