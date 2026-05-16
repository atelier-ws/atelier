---
description: "Use when: recording a run outcome, completion summary, validation result, or observable run facts."
allowed-tools: "mcp__atelier__record"
---

Record an Atelier run outcome.

1. Gather observable task, status, files touched, commands run, errors seen, validation results, diff summary, and output summary.
2. Call `record` with `agent` and `domain` set appropriately.
3. Report the record id if the tool returns one.

Never store secrets or hidden reasoning in a record.
