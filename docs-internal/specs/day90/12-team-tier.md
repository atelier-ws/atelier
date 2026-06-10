# Spec 12 — Team Tier (Outline)

> Phase 3. Where the revenue comes from. Outline only.

## Why

Team tier ($30/user/month) is the primary revenue lever. Engineering managers buy this for cost attribution, shared memory, audit, and SSO.

## What — user-visible

```bash
# Admin
$ atelier team init --name "Acme Engineering"
$ atelier team invite alice@acme.com bob@acme.com
$ atelier team usage --since 30d
  alice@acme.com   $452.20   62 sessions
  bob@acme.com     $381.10   58 sessions
  total:           $833.30  120 sessions

# User
$ atelier team join <invite-code>
$ atelier memory list --shared       # team-shared facts
$ atelier memory share <fact-id>     # promote local fact to team
```

## Pillars

1. **Cost attribution** — per-user spend across all vendors
2. **Shared memory** — opt-in facts visible to all team members
3. **SSO** — Google Workspace, Okta, generic SAML
4. **RBAC on memory** — admin can see all, member sees own + shared
5. **Audit log** — exportable JSON of all decisions, facts, sessions

## Where — outline

- Builds on spec 06 (sync) — team workspace is a shared sync namespace
- Builds on spec 08 (audit) — team audit log is multi-user variant
- Web dashboard (spec 10) gets a team view

## Out of scope (this outline)

- **Team-specific routing policies.** ("Always use Gemini for reads.") Future.
- **Approval workflows on memory writes.** Future.
- **Cost budgets / alerts.** Future.

## Open questions to resolve before executing

1. Pricing — is $30/user the right number, or is $20 better for adoption?
2. SSO providers — Google + Okta minimum? Generic SAML for v1?
3. Data residency — EU teams need EU storage. Defer to enterprise?

## Status

- [ ] Outline — refine before execution
