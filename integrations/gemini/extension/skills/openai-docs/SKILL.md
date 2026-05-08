---
name: openai-docs
description: Use this skill when the user asks how to build with OpenAI products or APIs, needs current official docs with citations, wants help choosing the latest model for a use case, or needs model-upgrade or prompt-upgrade guidance. Prefer official OpenAI docs and keep migrations narrow.
---

# OpenAI Docs

Use this skill for OpenAI product documentation, model selection, model migration,
and prompt migration questions. Treat official OpenAI docs as the source of truth.

## Quick start

- Prefer official OpenAI docs tooling when it is available. Otherwise read only
  official OpenAI docs pages on `developers.openai.com` or `platform.openai.com`.
- For "latest model", "current default", or unspecified upgrade requests, fetch
  the latest-model guide first or run:

  ```bash
  python3 scripts/resolve-latest-model-info.py
  ```

- If the user names a target model explicitly, preserve that target. Mention newer
  guidance only as optional context.
- If remote docs are unavailable, use the bundled fallback notes in `references/`
  and disclose that they may drift.

## Workflow

1. Classify the request: docs lookup, model selection, model upgrade, or prompt
   upgrade.
2. Read the smallest official doc set that answers the question. Do not widen the
   search if one page is sufficient.
3. For model upgrades, keep changes narrow: update active model defaults and prompt
   text directly tied to that model contract.
4. Do not widen a model or prompt migration into SDK, auth, shell, IDE, plugin, or
   environment changes unless the user asked for that separately.
5. For GPT-5.5 prompt upgrades, prefer outcome-first prompts, shorter instructions,
   explicit success criteria, explicit stopping rules, and concrete validation.
6. For tool-heavy or multi-turn workflows, verify preambles, `phase` handling, and
   assistant-item replay behavior before declaring the migration complete.
7. If the task only touches Atelier's own reasoning loop or Codex host packaging,
   do not claim that a GPT-5.5 migration is required unless there is an actual
   OpenAI-backed model or prompt surface being changed.

## Reference map

- Official latest-model guide:
  `https://developers.openai.com/api/docs/guides/latest-model.md`
- Official GPT-5.5 migration guide:
  `https://developers.openai.com/api/docs/guides/upgrading-to-gpt-5p5`
- Official prompt guidance:
  `https://developers.openai.com/api/docs/guides/prompt-guidance?model=gpt-5.5`
- Bundled fallback notes:
  - `references/latest-model.md`
  - `references/upgrade-guide.md`
  - `references/prompting-guide.md`
- Helper script:
  - `scripts/resolve-latest-model-info.py`

## Quality rules

- Official OpenAI docs win over bundled notes.
- Keep migrations behavior-preserving unless the user asked for broader changes.
- Prefer prompt-only upgrades before wider code changes when the issue is mostly
  prompting behavior.
- Do not invent pricing, availability, model features, parameter changes, or
  breaking changes.
- If docs and repo behavior disagree, state the conflict and stop before making a
  broad edit.