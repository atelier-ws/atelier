---
description: "Use when: running Atelier evals, rubric checks, verification gates, or validation cases."
allowed-tools: "Bash(atelier eval *), Bash(atelier proof *), mcp__atelier__verify"
---

Run or explain Atelier evaluation gates.

1. Identify the requested eval, proof, or rubric.
2. Prefer non-mutating commands and JSON output when available.
3. Summarize pass/fail status, failed checks, and the next concrete repair.

Do not mark an eval as passing unless the command or `verify` result says it passed.