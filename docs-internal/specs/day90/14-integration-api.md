# Spec 14 — Integration API (Outline)

> Phase 3. Ecosystem play. Outline only.

## Why

Once Atelier has the cross-vendor data, other tools want to integrate. IDE plugins, observability platforms, FinOps tools, internal dashboards — all benefit from an API that exposes Atelier's insights.

This is a moat-deepener: once integrations exist, switching cost rises.

## What — user-visible

```bash
$ atelier api keys create --name "vscode-plugin"
Key: atk_live_a8c2... (copy now, won't show again)

$ curl https://atelier.dev/api/v1/sessions/recent \
    -H "Authorization: Bearer atk_live_a8c2..."
```

Endpoints (read-only v1):
- `/api/v1/sessions` — list, filter
- `/api/v1/sessions/<id>` — single session
- `/api/v1/insights` — aggregated metrics
- `/api/v1/memory` — facts
- `/api/v1/outcomes` — outcome data
- `/api/v1/recommendations` — get a route recommendation for a hypothetical turn

## Where — outline

- Builds on web dashboard's API (spec 10), adds auth + rate limits
- Separate `atelier-api` service or extends `atelier-cloud`

## Partner integration targets

In rough order:

1. **VSCode plugin** — show cost in status bar, suggest model
2. **Vercel / Render** dashboards — show AI spend per project
3. **FinOps tools** (Vantage, CloudZero) — feed AI cost into their pipelines
4. **Slack / Teams bots** — daily cost reports in chat

## Open questions

1. Rate limits — per-key per-minute? Per-account per-day?
2. Pricing — free up to N requests/day, then?
3. OAuth vs API keys? Both?

## Status

- [ ] Outline — refine before execution
