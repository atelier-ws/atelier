# GPT-5.5 prompt migration notes

This is a fallback summary. Re-check the official prompting guide before using it
as final guidance.

## Core changes

- Prefer shorter, outcome-first prompts over long process-heavy prompt stacks.
- Keep personality and collaboration guidance short and explicit.
- State success criteria, stopping rules, evidence rules, and output shape.
- Remove step-by-step process instructions unless the exact path is part of the
  product contract.
- Use structured outputs for schemas when possible instead of describing schemas in
  prose.
- Drop the current date from prompts unless non-UTC or business-specific date
  context is required.

## Tool-heavy workflows

- Start with a short visible preamble before tool calls when the task is multi-step
  or long-running.
- Preserve assistant-item `phase` values if the application manually replays prior
  assistant output.
- Put most tool-specific guidance into tool descriptions rather than global prompt
  text.
- Ask the model to run validation after edits or other observable side effects.

## Retrieval and evidence

- Use the minimum evidence sufficient to answer correctly.
- Add retrieval budgets and stop searching once the core request is supported.
- Cite or link the official docs pages used for factual claims.