# Atelier plans & pricing

Atelier is **open-core** and **local-first**. The entire runtime is Apache-2.0
and runs on your machine — nothing is sent to a license server, and there is no
phone-home. The **Free** plan is genuinely useful on its own (grounded code
intelligence, packaging, memory, and the optimization *recommendations*). The
paid **Pro / Team / Enterprise** plans unlock the control surfaces that *apply*
the savings engine and the full savings dashboard.

> **Prices below are suggestions.** They are not hard-coded anywhere in the
> client — you set the real amounts when you create your Stripe Payment Links.
> The client only checks *which plan* a license grants, never the price.

## At a glance

| Capability                                                   | Free | Pro | Team | Enterprise |
| ------------------------------------------------------------ | :--: | :-: | :--: | :--------: |
| Grounded code intelligence (`search`/`grep`/`read`/`node`/…) |  ✅  | ✅  |  ✅  |     ✅     |
| Host packaging, agents, skills, `atelier init`               |  ✅  | ✅  |  ✅  |     ✅     |
| Local memory / recall (single repo)                          |  ✅  | ✅  |  ✅  |     ✅     |
| See optimization recommendations (`atelier optimize`)        |  ✅  | ✅  |  ✅  |     ✅     |
| Default savings summary (`atelier savings`)                  |  ✅  | ✅  |  ✅  |     ✅     |
| **Apply** an optimization policy (`atelier optimize apply`)  |  —   | ✅  |  ✅  |     ✅     |
| Full savings dashboard (`atelier savings --deep`)            |  —   | ✅  |  ✅  |     ✅     |
| Context compression / prefix-cache / scoped-context          |  —   | ✅  |  ✅  |     ✅     |
| Model routing & cross-vendor routing                         |  —   | ✅  |  ✅  |     ✅     |
| Optimize more than one repository                            |  —   | ✅  |  ✅  |     ✅     |
| Multiple seats / shared billing                              |  —   | —   |  ✅  |     ✅     |
| SSO, priority support, custom terms                          |  —   | —   |  —   |     ✅     |

The Pro capability keys are the contract in
[`features.py`](../src/atelier/core/capabilities/licensing/features.py)
(`PRO_FEATURES`); the plans that unlock them (`pro`, `team`, `enterprise`) are in
[`models.py`](../src/atelier/core/capabilities/licensing/models.py)
(`PRO_PLANS`).

## Free — $0

**For:** anyone trying Atelier, open-source projects, and developers who want
grounded code intelligence without paying.

You get the whole local runtime: the MCP server and all code-intelligence tools,
host packaging for every supported agent (Claude Code, Codex, Copilot, …),
agents/skills, single-repo memory, and the cost tracker. You can run
`atelier optimize` to **see** exactly what the savings engine *would* change and
how much it *would* save — you just can't apply it automatically or open the deep
dashboard.

No account, no key, no network call. Free is the default state of every install.

## Pro — for individual developers

**For:** a single developer who wants the savings engine to actually run.

Everything in Free, **plus** every gated capability: apply optimization policies,
the full savings dashboard, context compression, prefix-cache planning,
scoped-context pruning, per-session budget optimization, automatic model routing
and cross-vendor routing, and optimizing more than one repository.

| Billing | Suggested price | Notes                               |
| ------- | --------------- | ----------------------------------- |
| Monthly | **$9 / mo**     | Stripe subscription; cancel anytime |
| Annual  | **$90 / yr**    | ~2 months free vs monthly           |

A Pro license covers one person across all their machines (activate the same key
anywhere). See [Billing terms](#billing-terms) for how each maps to expiry.

## Team

**For:** a small team that wants shared billing and one license to manage.

Everything in Pro for every member of the team, billed together.

| Billing         | Suggested price       |
| --------------- | --------------------- |
| Per seat / mo   | **$8 / seat** (min 3) |
| Per seat / year | **$80 / seat**        |

Team licenses carry the `team` plan, which unlocks the same Pro capability set.

## Enterprise

**For:** organizations that need procurement, SSO, an invoice, or custom terms.

Everything in Team, plus SSO, priority support, a signed agreement, and optional
self-hosting of the issuer. **Pricing: custom — contact sales.**

Enterprise licenses carry the `enterprise` plan.

## Billing terms

Both plans are Stripe subscriptions. The issuer derives a license's expiry from
the purchase ([`termToExpiry`](../services/license-issuer/src/index.ts)):

| Term        | Stripe mode  | Expiry baked into the key |
| ----------- | ------------ | ------------------------- |
| **Annual**  | subscription | now + ~13 months (grace)  |
| **Monthly** | subscription | now + ~35 days (grace)    |

Subscriptions **auto-renew**: each successful Stripe renewal re-issues the *same*
license row with a fresh expiry and re-emails the key, so an active subscriber
never has to re-activate. If a subscription is cancelled or a charge is refunded,
the issuer revokes the license and stops renewing; the key simply lapses at its
current expiry and the install gracefully falls back to **Free**.

## How to buy & activate

1. **Buy** — open the Pro purchase link (`atelier license` upsells point at it;
   set your own with the `ATELIER_PRO_URL` env var or the default
   `https://atelier.ws/pro`). Pay through the Stripe Payment Link.
2. **Receive** — the Cloudflare Worker issuer signs an Ed25519 license and emails
   you the key. (See the issuer
   [README](../services/license-issuer/README.md).)
3. **Activate** —

   ```bash
   atelier license activate <key>   # verify + store at ~/.atelier/license.key
   atelier license status           # show plan, expiry, unlocked features
   atelier license deactivate       # revert to Free
   ```

   In CI or containers, set `ATELIER_LICENSE=<key>` instead of activating a file.

## FAQ

**Does activation require internet?** No. Verification is offline Ed25519 — the
public key is embedded in the client. You only need the network to *buy* (Stripe)
and to *receive* the emailed key.

**What happens when my license expires?** Nothing breaks. The gated control
surfaces re-lock and the install behaves exactly like Free again. Your code,
memory, and config are untouched.

**Can I use one key on multiple machines?** Yes for Pro (one person, many
machines). Team/Enterprise are sized by seats.

**Refunds?** A Stripe refund triggers automatic revocation on the next webhook —
no manual key-chasing required.

**Why is Free so capable?** Because the honest moat is the closed issuer and the
savings engine itself, not DRM on your local code. Free should be good enough to
trust; Pro should be worth it because it *runs* the engine for you. See
[`docs/licensing.md`](./licensing.md) for the technical design.
