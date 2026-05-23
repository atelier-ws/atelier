---
description: "Use when: you want a general-purpose coding pass delegated to Claude Sonnet 4.6."
---

Route the current task to a general-purpose implementation agent on Claude Sonnet 4.6.

1. First, print the exact runtime model ID currently being used.
2. Restate the user goal and acceptance target in 1-2 lines.
3. Hard requirement: perform implementation only through delegated Sonnet execution. Do not implement inline on non-Sonnet runtime.
4. Delegate work with:
   - `agent_type: "general-purpose"`
   - `model: "claude-sonnet-4.6"`
5. If Sonnet delegation is unavailable, stop and report the block explicitly.
6. Apply returned edits/results, then continue normal workflow.

Use this skill for multi-file changes, complex debugging, or when high-quality reasoning is needed.
