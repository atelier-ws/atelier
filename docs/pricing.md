# Atelier plans & pricing

Atelier is **open-core** and **local-first**: the whole runtime is Apache-2.0 and
runs on your machine. **Free** is a genuinely
useful coding-agent runtime on its own. **Pro** unlocks the leverage — fast search
and indexing across large repos, cross-session memory, the savings engine, and
model routing. **Enterprise** adds very-large-repo scale, shared team context,
and governance.

> **Prices below are suggestions.** They are not hard-coded in the client — you
> set the real amounts in your Stripe Payment Links. The client only checks
> *which plan/features* a license grants, never the price.

## At a glance

| Capability                                                  | Free | Pro | Enterprise |
| ----------------------------------------------------------- | :--: | :-: | :--------: |
| Code-nav tools (`read`/`grep`/`search`/`edit`/…)     |  ✅  | ✅  |     ✅     |
| Host packaging, agents, skills, `init`; benchmarks          |  ✅  | ✅  |     ✅     |
| Repo map + context engine (small repos)                     |  ✅  | ✅  |     ✅     |
| Headline savings number ("you'd save $X")                   |  ✅  | ✅  |     ✅     |
| Zoekt fast search · large-repo indexing · projection VFS     |  —   | ✅  |     ✅     |
| Session recall (all past sessions) · cross-vendor memory     |  —   | ✅  |     ✅     |
| Reasoning library (procedures, lessons, knowledge base)     |  —   | ✅  |     ✅     |
| Savings engine: apply + full breakdown + compression/budget |  —   | ✅  |     ✅     |
| Model routing (proxy daemon · cross-vendor · quality)        |  —   | ✅  |     ✅     |
| Multi-repo · multi-worktree swarm                           |  —   | ✅  |     ✅     |
| Very large repos, no index caps · shared team context       |  —   | —   |     ✅     |
| Governance · audit export · retention · SSO                  |  —   | —   |     ✅     |

Feature keys: `src/atelier/core/capabilities/licensing/features.py`
(`PRO_FEATURES`; `ENTERPRISE_FEATURES` is the Enterprise-only subset).

## Free — $0

**For:** anyone trying Atelier, open-source work, and developers who want a
grounded coding-agent runtime without paying.

You get the full local runtime that makes any agent better: the code-navigation
MCP tools, host packaging for every supported agent, single-repo memory,
benchmarks, and a project snapshot. The
context engine and repo map work on normal-size repos. You also see the
**headline savings number** — how much Atelier *would* save you — which is the
hook to upgrade.

No account, no key, no network call. Free is the default state of every install.

## Pro — for individual developers

**For:** a developer who wants Atelier's leverage on real, large codebases.

Everything in Free, **plus:**

- **Search & indexing at scale** — Zoekt-backed fast search, the native context
  engine + ANN symbol index for large repos, the projection/minification VFS, and
  indexing across **more than one repository**.
- **Memory** — semantic **recall over all your past sessions**, and **unified
  cross-vendor memory** across Claude, Codex, and Gemini.
- **Reasoning library** — reusable procedures, promoted lessons, and the review
  knowledge base.
- **Savings engine** — apply optimization policies, the full savings
  breakdown/dashboard, context compression/dedup, prefix-cache planning,
  scoped-context pruning, and the per-session budget optimizer.
- **Model routing** — the local routing proxy daemon, cross-vendor routing, and
  quality-gated routing.
- **Orchestration** — multi-worktree swarm runs.

| Billing | Suggested price | Notes                               |
| ------- | --------------- | ----------------------------------- |
| Monthly | **$19 / mo**    | Stripe subscription; cancel anytime |
| Annual  | **$190 / yr**   | ~2 months free vs monthly           |

One person, up to three active devices. Replacing a device is immediate: remove
an existing device when prompted, then activate the new one with no cooldown.

## Enterprise — contact us

**For:** teams and organizations with very large repos, shared-context needs, or
compliance requirements.

Everything in Pro, **plus:**

- **Very large repositories** with no index or symbol caps.
- **Shared team context** across repositories (unified memory shared across the
  team, not just one machine).
- **Governance** — policy enforcement, audit export, retention/redaction, and SSO.

**Pricing: custom — [contact us](https://atelier.ws/enterprise).** Enterprise
licenses carry the `enterprise` plan, which unlocks the Enterprise-only keys on
top of the full Pro set.

## Billing terms

Pro is a Stripe subscription. The issuer derives a license's expiry from the
purchase ([`termToExpiry`](../services/license-issuer/src/index.ts)):

| Term        | Stripe mode  | Expiry baked into the key |
| ----------- | ------------ | ------------------------- |
| **Annual**  | subscription | now + ~13 months (grace)  |
| **Monthly** | subscription | now + ~35 days (grace)    |

Subscriptions **auto-renew**: each successful renewal re-issues the same license
with a fresh expiry and re-emails the key. On cancellation or refund the issuer
revokes the license; the key lapses at its current expiry and the install
gracefully falls back to **Free**.

## How to buy & activate

1. **Buy** — open the Pro purchase link (`atelier license` upsells point at it;
   override with `ATELIER_PRO_URL`). Pay through the Stripe Payment Link.
2. **Receive** — the Cloudflare Worker issuer signs an Ed25519 license and emails
   you the key. (See the issuer [README](../services/license-issuer/README.md).)
3. **Activate** —

   ```bash
   atelier license activate <key>   # enroll this device and store its lease
   atelier license status           # show plan, expiry, unlocked features
   atelier license deactivate       # revert to Free
   ```

   In CI or containers, set `ATELIER_LICENSE=<key>` instead.

## FAQ

**Does activation require internet?** Yes. Initial activation enrolls the device
with the license issuer. The signed lease is then checked locally and refreshes
automatically every 30 days, with a 7-day offline grace period.

**What happens when my license expires?** Nothing breaks: the gated surfaces
re-lock and the install behaves like Free again. Your code, memory, and config
are untouched.

**Can I use one key on multiple machines?** Yes, on up to three active devices
for Pro. A fourth activation lists the existing devices and asks you to remove
one first; the replacement activates immediately.

**Refunds?** A Stripe refund triggers automatic revocation on the next webhook.

**Why is Free so capable?** The honest moat is the closed issuer + the private
`pro/` overlay (Free installs don't have the paid code) + being the maintainer —
not DRM on local code. Free should be good enough to trust. See
[`docs/licensing.md`](./licensing.md) for the technical design.
