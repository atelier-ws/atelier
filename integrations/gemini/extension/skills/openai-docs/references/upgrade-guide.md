# GPT-5.5 upgrade checklist

Use this as a fallback summary. Official docs remain the source of truth.

## When an upgrade is actually needed

- Upgrade only if the repo has an active OpenAI model default, an OpenAI prompt
  stack, or OpenAI API orchestration you intend to change.
- Do not force a GPT-5.5 migration onto unrelated tooling, host packaging, or
  non-OpenAI integrations.

## Narrow migration plan

1. Update the target model slug to `gpt-5.5`.
2. Prefer the Responses API for reasoning, tool-calling, and multi-turn flows.
3. Re-evaluate `reasoning.effort`, starting with `low` or `medium`.
4. Re-evaluate `text.verbosity`, often starting with `low` for concise answers.
5. Rewrite prompts toward outcome-first guidance rather than process-heavy stacks.
6. Verify preambles and `phase` handling if your app manually replays assistant
   items.
7. Benchmark quality, latency, and token cost before widening the migration.

## Changes to avoid unless separately requested

- SDK upgrades unrelated to the target model change
- Auth or credential changes
- IDE, plugin, shell, or CI workflow changes
- Historical docs, eval baselines, fixtures, or examples that are not part of the
  active OpenAI path