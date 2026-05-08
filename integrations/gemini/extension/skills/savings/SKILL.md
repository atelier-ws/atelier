---
description: Report Atelier-attributed savings — calls avoided, tokens saved, bad plans blocked, rescue events, rubric failures caught.
---

Show Atelier savings for this workspace.

1. Run the host CLI: `atelier savings --json` (it reads `.atelier/`
   smart-tool counters and walks the run ledgers).
2. Parse the JSON and render a one-line per metric summary:
   - `calls_avoided`
   - `tokens_saved`
   - `bad_plans_blocked`
   - `rescue_events`
   - `rubric_failures_caught`
3. Add a one-line caveat: counters are local to this workspace and reset
   when `.atelier/` is cleared.

Do not invent metrics. Do not extrapolate dollar figures.
