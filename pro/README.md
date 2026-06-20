# pro/ — Atelier Pro overlay (proprietary)

**Closed source. Lives in this repo but is stripped from the public release.**

This directory holds the paid side of the open-core split:

- `src/atelier_pro/` — the **Pro overlay** wheel (`atelier-pro`): the paid engine
  activation surfaces. Distributed only to licensed Pro customers.

## How it stays private

`pro/` is listed in [`release/private-paths.txt`](../release/private-paths.txt).
When the public snapshot is generated (`scripts/mirror.py` /
`scripts/publish-public.sh`), every path in that denylist — including `pro/` — is
stripped from the tree, so the open-source repo never contains this code. It is
**tracked** in the private repo (not gitignored); the strip happens at publish
time, not via `.gitignore`.

The public wheel also never ships it: the core build only packages
`src/atelier` (`pyproject.toml`), so `atelier_pro` is a separate distribution.

## How the overlay works

The open-source core never imports Pro code directly. It soft-imports the overlay
through `atelier.core.capabilities.pro_bridge`:

- **No overlay installed** (every Free install / public snapshot) → `pro_bridge`
  returns `None`/`False`, and the core falls back to Free behavior silently.
- **Overlay installed + valid license** → the gated path runs.

A Pro path runs only when **both** agree:

1. the code is physically present (`atelier_pro` importable, feature in
   `atelier_pro.FEATURES`), and
2. a valid Ed25519 license grants the feature (`licensing.has_feature`).

A leaked overlay can't run without a key; a key with no overlay has nothing to
run.

## Develop / build

```bash
uv pip install -e pro            # install atelier_pro against the local core
python -c "import atelier_pro, atelier_pro.optimizer"   # smoke check
cd pro && python -m build        # -> dist/atelier_pro-*.whl for Pro customers
```

With the overlay installed **and** a Pro license activated
(`atelier license activate <key>`), the gated commands light up:
`atelier optimize apply ...` and `atelier savings --deep`.

## Add another Pro feature

1. Add the feature key to `PRO_FEATURES` in the **core**
   (`src/atelier/core/capabilities/licensing/features.py`).
2. Add the same key to `FEATURES` in `pro/src/atelier_pro/__init__.py`.
3. If the feature *runs code*, add a submodule `pro/src/atelier_pro/<key>.py`
   and call it from the core via `licensing.pro_impl("<key>")` at the seam, with
   a Free fallback. If it's a pure unlock/view, gate the seam on
   `licensing.feature_active("<key>")` — presence + license is the entitlement.
