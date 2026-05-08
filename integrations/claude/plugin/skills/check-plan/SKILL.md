---
description: "Use when: validating an implementation plan, checking a plan before edits, or asking whether a plan is blocked."
allowed-tools: "mcp__atelier__lint"
---

Validate a plan with Atelier.

1. Collect the task, plan steps, files, domain, tools, and known errors.
2. Call `lint`.
3. If blocked, show the blocking reason and the suggested replacement plan.
4. If warnings exist, list them and update the plan before work continues.

Do not edit code before a blocked plan is corrected.
