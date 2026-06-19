# Licensing & Pro features (open-core)

Atelier is open-core: the entire runtime is Apache-2.0 and runs locally. A small
set of **paid ("Pro") control surfaces** are gated behind an offline-verified
license. The split is designed so the Free tier is genuinely useful (and already
delivers most of the token savings) while the incremental optimizer and the full
savings dashboard are paid.

- **Client (Apache-2.0):** `src/atelier/core/capabilities/licensing/` — verifies
  and stores license keys, answers "is this feature unlocked?".
- **Issuer (proprietary):** `services/license-issuer/` — a Cloudflare Worker that
  turns a Stripe payment into a signed key and emails it. See its
  [README](../services/license-issuer/README.md).

Verification is **offline Ed25519**: no license server, no phone-home. The
private signing key lives only in the Worker; the public key is embedded in the
client.

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
(for self-issued keys or testing).

## The entitlement contract

Every gate calls one tiny API:

```python
from atelier.core.capabilities import licensing

licensing.is_pro()                 # bool
licensing.has_feature("optimizer") # bool — non-Pro keys are always True
licensing.require("optimizer")     # raises FeatureLocked if not unlocked
```

## Gating a new feature

1. Add a key + description to `PRO_FEATURES` in `features.py`.
2. At the seam that *activates* the capability, call `licensing.require("key")`
   (CLI: catch `FeatureLocked` and raise `click.ClickException` with an upgrade
   hint). Prefer gating the **write/apply/activate** action, not read-only
   previews — let users measure the value before they pay for it.

Current gates (reference): `atelier optimize apply` and `atelier savings --deep`
in `src/atelier/gateway/cli/commands/savings.py`.

> Gating is intentionally shallow and honest. The enforceable moat is that the
> issuer is closed and the savings engine is the differentiated IP — not DRM on
> local code.
