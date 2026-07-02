# Licensing & Pro features (open-core)

Atelier is open-core: the entire runtime is Apache-2.0 and runs locally. A small
set of **paid ("Pro") control surfaces** are gated behind the signed-in
account's plan. The split is designed so the Free tier is genuinely useful (and
already delivers most of the token savings) while the incremental optimizer and
the full savings dashboard are paid.

> Looking for the customer-facing plan breakdown and prices? See
> [**Plans & Pricing**](./pricing.md). This document is the technical design.

- **Client (Apache-2.0):** `src/atelier/core/capabilities/licensing/` — holds
  the OAuth session and answers "is this feature unlocked?".
- **Pro overlay (proprietary):** the `atelier_pro` package under `pro/` — a
  separate wheel holding the paid engine activation surfaces. Tracked in this
  repo but excluded from public releases via `release/public-paths.txt`. The
  core never imports it directly; it soft-imports it through `pro_bridge`, so
  it's absent on every Free install. See [`pro/README.md`](../pro/README.md).
- **Auth server (proprietary):** the landing site's `/api/auth/*` functions
  plus the Stripe webhook. Google OAuth signs the user in, Stripe payments set
  the account's plan, and `/api/auth/me` reports `{email, plan, device_id}` to
  the CLI.

## How entitlement works

`atelier login` runs a browser OAuth flow against the auth server and stores a
session token at `~/.atelier/auth_token` (mode `0600`; override with the
`ATELIER_AUTH_TOKEN` env var — handy for CI). Entitlement checks read the plan
from `/api/auth/me`, cached on disk for 24 hours (`~/.atelier/auth_user.json`),
so normal operation makes at most one auth call a day. If the server is
unreachable and no fresh cache exists, gated surfaces stay locked and the check
retries hourly; Free surfaces are never affected.

`atelier logout` deletes the session and reverts to Free. There are no offline
license keys, no device-bound leases, and no local crypto — the account's plan
is the single source of truth.

**Two walls, defense in depth.** A Pro path runs only when *both* agree: the
code is physically present (the `atelier_pro` overlay is installed and declares
the feature) **and** the signed-in account's plan grants it. A leaked overlay
can't run without a Pro account; a Pro account with no overlay has nothing to
run.

| Overlay installed? | Pro plan? | Result                          |
| :----------------: | :-------: | ------------------------------- |
|         no         |    no     | **Free** — silently skips       |
|         no         |    yes    | Free behavior (nothing to run)  |
|       **yes**      |    no     | **Locked** (handles a leak)     |
|        yes         |    yes    | **Pro**                         |

## Free vs Pro vs Enterprise

| Capability                                                  | Free | Pro | Ent |
| ----------------------------------------------------------- | :--: | :-: | :-: |
| Code-nav MCP tools (`read`/`grep`/`search`/`edit`/…) |  ✅  | ✅  | ✅  |
| Host packaging, agents, skills, `init`; benchmarks          |  ✅  | ✅  | ✅  |
| Repo map + context engine (small repos)                     |  ✅  | ✅  | ✅  |
| Headline savings number                                     |  ✅  | ✅  | ✅  |
| Zoekt fast search; large-repo indexing; projection VFS      |  —   | ✅  | ✅  |
| Session recall + cross-vendor memory                        |  —   | ✅  | ✅  |
| Reasoning library (procedures, lessons, knowledge)          |  —   | ✅  | ✅  |
| Savings engine: apply + full breakdown + compression/budget |  —   | ✅  | ✅  |
| Model routing (daemon, cross-vendor, quality)               |  —   | ✅  | ✅  |
| Multi-repo; multi-worktree swarm                            |  —   | ✅  | ✅  |
| Very large repos (no caps); shared team context             |  —   | —   | ✅  |
| Governance, audit export, retention, SSO                    |  —   | —   | ✅  |

The feature keys are in `src/atelier/core/capabilities/licensing/features.py`
(`PRO_FEATURES`, with `ENTERPRISE_FEATURES` the Enterprise-only subset). For the
customer-facing plans and prices see [Plans & Pricing](./pricing.md).

## Signing in

```bash
atelier login          # browser OAuth; stores the session token
atelier status --auth  # show email, plan, and device slots
atelier logout         # revert to Free (local anonymous trial)
```

A Pro account supports up to **three active CLI devices**; the auth server
tracks the slots. `ATELIER_PRO_URL` overrides the "buy" link shown in
upsells — point it straight at your Stripe Payment Link.

## The entitlement contract

Every gate calls one tiny API:

```python
from atelier.core.capabilities import licensing

licensing.is_pro()                    # bool
licensing.has_feature("optimizer")    # plan only — non-Pro keys are always True
licensing.require("optimizer")        # raises FeatureLocked if the plan doesn't grant it
licensing.feature_active("optimizer") # plan AND overlay installed (use this at seams)
licensing.pro_impl("optimizer")       # the atelier_pro module to run, or None
```

- `has_feature` / `require` check the **plan** only.
- `feature_active` checks the **plan and** that the `atelier_pro` overlay is
  installed — the right test for a seam that should silently fall back to Free.
- `pro_impl` returns the overlay module that actually runs the feature (or
  `None`); the seam calls into it, e.g. `pro_impl("optimizer").apply_policy(...)`.

## Gating a new feature

1. **Core:** add the key + description to `PRO_FEATURES` in `features.py`.
2. **Overlay:** add the same key to `FEATURES` in `atelier_pro/__init__.py`. If
   the feature *runs code*, add a submodule `atelier_pro/<key>.py` holding the
   paid logic (importing the public compute from the core).
3. **Seam:** at the point that *activates* the capability, branch on the
   overlay:

   ```python
   impl = licensing.pro_impl("optimizer")
   if impl is None or not licensing.has_feature("optimizer"):
       ...  # Free fallback — silently degrade
   else:
       impl.apply_policy(...)  # Pro path
   ```

   For a pure unlock/view (no separate private code), branch on
   `licensing.feature_active("<key>")` instead. Prefer gating the
   **write/apply/activate** action, not read-only previews — let users measure
   the value before they pay for it.

Current gates (reference): `atelier optimize apply` (runs `atelier_pro.optimizer`
via `pro_impl`) and `atelier savings --deep` (`feature_active`) in
`src/atelier/gateway/cli/commands/savings.py`.

## Open-core layout (what's public vs private)

Everything lives in **one repo**. Only paths listed in
`release/public-paths.txt` are included in the public mirror
(`scripts/mirror.py`). Everything else is private by default — a new directory
never leaks unless it's explicitly allowlisted.

| Public (included via `public-paths.txt`)           | Private (excluded by default)                                      |
| -------------------------------------------------- | ------------------------------------------------------------------ |
| Whole runtime, MCP server, SDK, CLI                | `pro/` — the `atelier_pro` overlay (paid surfaces)                 |
| License **client** (`licensing/`, `pro_bridge`)    | `internal/`, `docs-internal/`, `.planning/` (strategy)             |
| Public compute the overlay calls into              | `services/` — auth/payments backend (Stripe, D1)                   |
| `docs/`, `integrations/`, `tests/`, benchmarks     | `deploy/`, `release/` (publish machinery)                          |
| `frontend/`, `landing/`, `docs-site/`              | Stripe secrets (never committed)                                   |

The `atelier_pro` wheel is built from `pro/` and distributed only to licensed
customers; the public snapshot never contains `pro/`.
