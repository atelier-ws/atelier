---
description: "Use when: recording an Atelier trace, completion summary, validation result, or observable run outcome."
allowed-tools: "mcp__atelier__trace"
---

Record an Atelier trace.

1. Gather observable task, status, files touched, commands run, errors seen, validation results, diff summary, and output summary.
2. Call `trace` with `agent` and `domain` set appropriately.
3. Report the trace id if the tool returns one.

Never store secrets or hidden reasoning in a trace.