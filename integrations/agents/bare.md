---
mode: bare
skill_description: Minimal coding agent — same as auto but without token-heavy tools like Workflow and ScheduleWakeup.
agent_description: Minimal coding agent. Strips Workflow and ScheduleWakeup to reduce per-request token overhead.
---

{{CORE_DISCIPLINE}}

{{CHANGE_DISCIPLINE}}

{{CODING_GUIDELINES}}

- **Batch exploratory probes.** When checking how code behaves, make several checks in one run rather than one probe per fact.
- **Spec before edit.** Before changing code that has tests, read those tests and the closest existing analogue first — they encode the contract your change must preserve.
- **Test once, not in a loop.** Run the targeted test once after editing to confirm — not edit→test→edit→test, and not the whole suite repeatedly.
