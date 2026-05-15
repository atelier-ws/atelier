# Spec 13 — Public Benchmark Leaderboard (Outline)

> Phase 3. Marketing engine. Outline only.

## Why

Weekly benchmark publication (spec 05) creates content. A public leaderboard at `atelier.dev/leaderboard` creates a **destination**. Developers bookmark it, return to it, share it.

This is also how we keep ourselves honest — published numbers can't be quietly walked back.

## What — user-visible

`atelier.dev/leaderboard`:

- Live-updating table: vendor × model × tool-class × cost-per-session × quality-score
- Historical chart: how each vendor's per-task cost has moved over 12 weeks
- "Best vendor for X" widget: pick a use case, see recommended vendor mix
- Methodology link, raw data download

Public. No auth needed. Mobile-friendly.

## Where — outline

- Builds on spec 05's publication pipeline output
- Frontend: same atelier-dashboard repo or separate
- Backend: static-site or thin API serving the latest `reports/` JSON

## Open questions

1. Should community-submitted benchmark runs appear on the leaderboard?
2. How do we prevent vendors from gaming the leaderboard?
3. Embed code so other blogs can include the leaderboard?

## Status

- [ ] Outline — refine before execution
