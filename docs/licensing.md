# Licensing & Pro features (open-core)

Atelier is open-core: the entire runtime is Apache-2.0 and runs locally. A small
set of **paid ("Pro") control surfaces** are gated behind an offline-verified
license. The split is designed so the Free tier is genuinely useful (and already
delivers most of the token savings) while the incremental optimizer and the full
savings dashboard are paid.

> Looking for the customer-facing plan breakdown and prices? See
> [**Plans & Pricing**](./pricing.md). This document is the technical design.

- **Client (Apache-2.0):** `src/atelier/core/capabilities/licensing/` — verifies
  and stores license keys, answers "is this feature unlocked?".
- **Pro overlay (proprietary):** the `atelier_pro` package under `pro/` — a
  separate wheel holding the paid engine activation surfaces. Tracked in this
  repo but stripped from public releases via `release/private-paths.txt`. The
  core never imports it directly; it soft-imports it through `pro_bridge`, so
  it's absent on every Free install. See [`pro/README.md`](../pro/README.md).
- **Issuer (proprietary):** `services/license-issuer/` — a Cloudflare Worker that
  turns a Stripe payment into a signed key and emails it. See its
  [README](../services/license-issuer/README.md).

Verification is **offline Ed25519**: no license server, no phone-home. The
private signing key lives only in the Worker; the public key is embedded in the
client.

**Two walls, defense in depth.** A Pro path runs only when *both* agree: the
code is physically present (the `atelier_pro` overlay is installed and declares
the feature) **and** a valid license grants it. A leaked overlay can't run
without a key; a key with no overlay has nothing to run.

| Overlay installed? | Valid license? | Result                          |
| :----------------: | :------------: | ------------------------------- |
|         no         |       no       | **Free** — silently skips       |
|         no         |      yes       | Free behavior (nothing to run)  |
|       **yes**      |       no       | **Locked** (handles a leak)     |
|        yes         |      yes       | **Pro**                         |

## Free vs Pro

| Capability                                                       | Free | Pro |
| ---------------------------------------------------------------- | :--: | :-: |
| Grounded code intelligence (`search`/`grep`/`read`/`node`/…)     |  ✅  | ✅  |
| Host packaging, agents, skills, `init`                           |  ✅  | ✅  |
| Local memory / recall (single repo)                              |  ✅  | ✅  |
| See optimization recommendations (`atelier optimize`)            |  ✅  | ✅  |
| **Apply** an optimization policy (`atelier optimize apply`)      |  —   | ✅  |
| Full savings breakdown (`atelier savings --deep`)                |  —   | ✅  |
| Model routing / cross-vendor routing                             |  —   | ✅  |

The Pro feature keys are defined in
`src/atelier/core/capabilities/licensing/features.py` (`PRO_FEATURES`).

## Using a license

```bash
atelier license activate <key>   # verify + store at ~/.atelier/license.key
atelier license status           # show plan, expiry, unlocked features
atelier license deactivate       # revert to Free
```

The `ATELIER_LICENSE` env var overrides the stored file (handy for CI and
containers). `ATELIER_LICENSE_PUBLIC_KEY` overrides the embedded public key
(for self-issued keys or testing). `ATELIER_PRO_URL` overrides the "buy" link
shown in upsells -- point it straight at your Stripe Payment Link.

## The entitlement contract

Every gate calls one tiny API:

```python
from atelier.core.capabilities import licensing

licensing.is_pro()                    # bool
licensing.has_feature("optimizer")    # license only — non-Pro keys are always True
licensing.require("optimizer")        # raises FeatureLocked if the license doesn't grant it
licensing.feature_active("optimizer") # license AND overlay installed (use this at seams)
licensing.pro_impl("optimizer")       # the atelier_pro module to run, or None
```

- `has_feature` / `require` check the **license** only.
- `feature_active` checks the **license and** that the `atelier_pro` overlay is
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

Everything lives in **one repo**. Private paths are listed in
`release/private-paths.txt` and stripped when the public snapshot is generated
(`scripts/mirror.py` / `scripts/publish-public.sh`).

| Public (kept in the snapshot)                   | Private (stripped via private-paths.txt)              |
| ----------------------------------------------- | ----------------------------------------------------- |
| Whole runtime, MCP server, SDK, CLI             | `pro/` — the `atelier_pro` overlay (paid surfaces)    |
| License **client** (`licensing/`, `pro_bridge`) | `internal/`, `docs-internal/`, `.planning/` (strategy)|
| Public compute the overlay calls into           | `release/`, `.github/workflows/` (publish machinery)  |
| `docs/`, `integrations/`, `tests/`, benchmarks  | Ed25519 **private** key + Stripe secrets (never committed) |

The `atelier_pro` wheel is built from `pro/` and distributed only to licensed
customers; the public snapshot never contains `pro/`. (The license **issuer**,
`services/license-issuer/`, stays public for transparency — it holds no secrets;
the signing key lives only in the deployed Worker.)

> The enforceable moat is the closed issuer (only it mints valid keys) plus the
> private overlay (Free installs don't have the paid code) — not DRM on local
> source. Keep the split honest: the Free tier should be good enough to trust.
