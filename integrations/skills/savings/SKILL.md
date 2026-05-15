---
description: Report Atelier-attributed savings — context compaction, model routing tier downgrades, calls avoided, tokens saved, and dollar totals.
---

Show Atelier savings for this workspace.

1. Run `atelier savings --json` and parse the result.
2. Render a summary with two distinct dimensions:

   **Context savings** (tokens + cost freed by compaction and tool-output reduction):
   - `tokens_saved` — context tokens kept out of the window
   - `calls_avoided` — redundant tool calls skipped
   - `cost_saved_usd` — dollar value of the above at current model pricing

   **Model routing savings** (cost reduction from tier downgrade, zero token change):
   - `routing_cost_saved_usd` — estimated savings vs opus-4-7 baseline when a cheaper tier was recommended
   - `routing_calls_downtiered` — number of tool calls routed to cheap/medium instead of expensive

3. Show totals: `total_saved = context_cost_saved + routing_cost_saved`.
4. Add a one-line caveat: counters are local to this workspace and accumulate in `.atelier/live_savings_events.jsonl`.

Do not invent metrics. Do not extrapolate beyond what the JSON returns.
