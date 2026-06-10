# M2 — Audit & fix silent `except Exception: pass`

> Risk: Low per-site, but requires judgment. 28 sites. Depends on M1 (lint rule
> exists so fixed files can drop their `per-file-ignores`).

## Problem

28 `except Exception: pass` blocks swallow errors with no signal. In an agent
runtime a failed memory write, telemetry emit, or ledger append vanishes
silently — exactly the failures you most want to see.

## Scope

In:
- Each of the 28 sites: decide intentional-suppress vs. should-surface.
  - Intentional (best-effort telemetry/cleanup): keep suppression but add
    `logger.debug("...", exc_info=True)` and a one-line comment on *why*.
  - Should-surface: narrow the exception type, log at `warning`/`error`, or
    re-raise.
- Remove each fixed file from the `BLE001` `per-file-ignores` added in M1.

Out:
- Broad `except Exception:` (non-`pass`) blocks — only the silent `pass` ones.

## Files

Enumerate fresh (don't trust a stale list):
```bash
grep -rn -A1 "except Exception" src --include='*.py' | grep -B1 "pass"
```

## Steps

1. Generate the site list with the command above.
2. For each site, read ~15 lines of surrounding context to classify it.
3. Apply the minimal fix (log+comment, or narrow+raise). Match local logging
   style — check how the module already obtains its logger.
4. After fixing all sites in a file, remove that file from the M1
   `per-file-ignores` for `BLE001`.
5. Re-run the enumeration; confirm count drops to 0 (or document any kept with
   an explicit `# noqa: BLE001` + reason).

## Validation

```bash
make lint && make typecheck && make test
uv run pytest tests/gateway/test_mcp_tool_handlers.py tests/gateway/test_p0_mcp_surfaces.py -q
```
If any touched module has dedicated tests, run them. Add a regression test where
a previously-swallowed error now surfaces, if cheap.

## Done when

- No silent `except Exception: pass` remain (or each survivor has an inline
  justified `# noqa: BLE001`).
- `BLE001` `per-file-ignores` shrink correspondingly.
