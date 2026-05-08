---
description: "Use when: reporting Atelier savings, calls avoided, tokens saved, bad plans blocked, rescue events, or rubric failures caught."
allowed-tools: "Bash(atelier savings *)"
---

Show Atelier savings for this workspace.

1. Run `atelier savings --json`.
2. Render calls avoided, tokens saved, bad plans blocked, rescue events, and rubric failures caught.
3. Add that counters are local to this workspace and reset if `.atelier/` is cleared.

Do not extrapolate dollar figures unless the command returns them.