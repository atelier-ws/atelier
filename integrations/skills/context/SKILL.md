---
description: Use at the start of every coding task to retrieve Atelier context, procedures, memory, and relevant run state.
argument-hint: "<task description>"
---

Retrieve Atelier context for the current task.

1. Ask for or infer the task, domain, files, tools, and errors.
2. Call the MCP tool `context` with the available fields:

   ```
   context({
     task: "<one-sentence task>",
     domain: "<domain or null>",
     files: ["<likely files>"],
     tools: ["<likely tools>"],
     errors: ["<known error messages>"]
   })
   ```

3. Summarize only the matched procedures, dead ends, required validations, and concrete run context that matter for the next step.

Keep the output short and action-oriented. Never include secrets, API keys, tokens, or hidden chain-of-thought.
