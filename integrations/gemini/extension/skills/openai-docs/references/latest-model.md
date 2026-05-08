# Latest model fallback

This file is a local fallback. Re-check official OpenAI docs before repeating any
of these details to a user.

As of 2026-05-07, the latest-model guide exposes this `latestModelInfo` block:

- Model: `gpt-5.5`
- Migration guide:
  `https://developers.openai.com/api/docs/guides/upgrading-to-gpt-5p5`
- Prompt guidance:
  `https://developers.openai.com/api/docs/guides/prompt-guidance?model=gpt-5.5`

Operational notes pulled from the same guide:

- Start migrations from a fresh prompt baseline instead of carrying forward every
  old instruction.
- GPT-5.5 defaults reasoning effort to `medium`; re-evaluate `low` before raising
  effort.
- For reasoning, tool use, or multi-turn work, prefer the Responses API.
- Use `text.verbosity` intentionally. `low` is a good starting point for concise
  answers.
- For tool-heavy flows, verify preambles, `phase` handling, and replay behavior.
- Do not add the current date to prompts unless business-specific date context is
  required.