# Atelier Pricing & Business Model

> Open-core, sync-and-team monetisation. Proven shape for dev infra (Tailscale, Vercel, Linear).

## Pricing tiers

| Tier | Price | Audience | What's included |
|------|-------|----------|-----------------|
| **Free** | $0 | Solo developers | All local features: routing, compact, memory adapters, single-machine, cost dashboard, terminal-only |
| **Pro** | $12 / month | Heavy individual users | Cross-machine sync (up to 3 machines), 6-month history, web dashboard, federated routing benefits |
| **Team** | $30 / user / month | Small engineering teams | Pro features + shared memory, per-user cost attribution, SSO, RBAC on memory, audit log |
| **Enterprise** | Custom, target $50–100 / user / month | 50+ seats | Team features + on-prem sync server, SOC2 reports, dedicated support, custom retention, audit export |

## Pricing logic

### Free tier
Has to be **genuinely good** — if it's a crippled trial, developers won't install. Free tier is the funnel:
- All routing and compact intelligence
- All three pillars work locally
- No artificial caps on session count or memory size
- Only restriction: single machine, no cloud sync

### Pro tier ($12/mo)
Targets developers spending more than ~$50/mo on AI tools. The conversion logic:
- "I'm spending $200/mo on Claude. Atelier shows me Gemini would have covered 40% of turns. $12 to sync this across machines is obvious."
- Sync is the wedge: Codex literally has no native solution; Claude Memory is per-project local
- 6-month history justifies the recurring spend (free tier keeps 30 days)

### Team tier ($30/user/mo)
This is **where the real revenue comes from.** Engineering managers buy this for:
- **Cost attribution** — see which engineer/team spent what on AI tools
- **Shared memory** — onboarding accelerator. New hire's Atelier already knows the codebase conventions
- **Audit trail** — required by infosec at most companies above 50 engineers
- **SSO** — required by IT at most companies above 100 engineers

### Enterprise (custom)
Don't chase before Team is repeating. Required to add:
- SOC2 Type II certification
- On-prem sync server option
- Custom data retention
- Dedicated CSM
- Procurement cycle (~6 months)

## Revenue projections

### Conservative (Year 1 — May 2026 to May 2027)

| Cohort | Users / customers | MRR contribution |
|--------|-------------------|------------------|
| Free | 10,000 installs | $0 |
| Pro | 500 ($12 × 500) | $6,000 |
| Team | 30 teams × 8 seats × $30 | $7,200 |
| Enterprise | 0 | $0 |
| **Total** | | **~$13,200 MRR** |

### Aggressive (Year 2 — May 2027 to May 2028)

| Cohort | Users / customers | MRR contribution |
|--------|-------------------|------------------|
| Free | 100,000 | $0 |
| Pro | 5,000 | $60,000 |
| Team | 300 teams × 10 seats × $30 | $90,000 |
| Enterprise | 5 contracts × $30K ARR | $12,500 |
| **Total** | | **~$162,500 MRR ($1.95M ARR)** |

Year 2 is the "raise or bootstrap" inflection.

## Unit economics

### Cost structure
- **Sync infrastructure**: cloud storage + encryption. Estimate $0.50/Pro user/month at scale.
- **Telemetry pipeline**: PostHog + GCP. Estimate $0.20/active free user/month, $1/Pro user/month.
- **Customer support**: minimal at Free tier (docs + community), 0.5 FTE per 100 Team customers.

### Gross margin target
- Pro tier: ~$10.30 contribution per user ($12 - $0.50 sync - $0.20 telemetry - $1 processing)
- Team tier: ~$26 contribution per user

**~85% gross margin at maturity** — standard for dev infra SaaS.

## What we don't charge for

Hard rule: **never charge for things developers expect to be free.**

- AI model costs — pass through, never markup
- Telemetry export — users own their data
- Read-only API access at Free tier
- Self-hosting the open-source binary

What this means in practice: if Anthropic raises Claude's price, our customers see the price; we don't take a cut and we don't get blamed.

## Anti-patterns we avoid

| Anti-pattern | Why it kills trust |
|---|---|
| Usage-based pricing (per-session, per-token) | Aligns us against the user; we'd be incentivised to NOT save them money |
| Marking up model costs | Users will discover it; lose trust permanently |
| Crippling Free tier to force upgrades | Developers detect this in 5 minutes and uninstall |
| Hiding pricing behind "Contact Sales" until Enterprise | Damages dev-trust signal at Pro and Team tiers |

## Pricing changes

- Lock Free tier features forever. **Things you can do in Free today, you can always do in Free.**
- Pro tier price can rise with feature value, but grandfather existing subscribers for 12 months.
- Team tier price reviewed annually; communicate 60 days ahead.

## Payment infrastructure

- **Stripe** for Pro and Team self-serve
- **Stripe Atlas / direct invoice** for Enterprise
- Annual discount: 2 months free on Pro and Team

## Refund policy

- Pro: 30-day no-questions refund
- Team: prorated refund any time
- Enterprise: contractual

## Open questions

- [ ] Should we offer a student / open-source-maintainer free Pro tier?
- [ ] Should there be a non-profit / education discount on Team?
- [ ] How do we handle developers spending under $20/mo on AI — are they our market?
