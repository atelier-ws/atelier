#!/usr/bin/env python3
"""Smoke-test whether the Atelier MCP `workflow` and `agent` runtime tools work.

Why this exists: the curated `atelier tools list` shows only an advertised subset,
so a tool can be *missing from that list yet fully callable by name* (it lives in
`TOOLS` but is in `HIDDEN_LLM_TOOLS`). This script checks the thing that actually
matters for the skills: are `workflow` and `agent` registered and dispatchable?

It uses the same in-process dispatch path the test suite trusts
(`atelier.gateway.sdk.mcp._LoopbackTransport`), so there is no stdio framing or
MCP-client setup to get wrong.

Two modes:
  (default) cheap, zero-cost, zero-execution: registration + visibility + the
            required input-schema fields for each runtime tool. Proves
            callable-by-name without spawning anything.
  --live    actually dispatch a trivial `agent` run and a 1-step `workflow` run
            through _LoopbackTransport. Costs a real model call and needs your
            provider credentials configured.

Run:
  uv run python scripts/smoke_runtime_tools.py
  uv run python scripts/smoke_runtime_tools.py --live

Exit code 0 if every runtime tool is registered (and, with --live, dispatched
without error); non-zero otherwise — so CI can gate on it.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

RUNTIME_TOOLS = ("workflow", "agent")


def _required_fields(spec: dict[str, Any]) -> list[str]:
    schema = spec.get("inputSchema") or spec.get("input_schema") or {}
    req = schema.get("required")
    if isinstance(req, list):
        return [str(x) for x in req]
    props = schema.get("properties")
    return sorted(props.keys()) if isinstance(props, dict) else []


def _live_args(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Build the smallest plausible valid payload for a real --live call."""
    if name == "agent":
        return {"prompt": "Reply with exactly one word: pong"}
    if name == "workflow":
        # `op` is the required field; op="run" with a 1-step prompt workflow.
        # Shapes vary, so this is best-effort — adjust to your run schema if it errors.
        return {
            "op": "run",
            "workflow": {"steps": [{"id": "ping", "prompt": "Reply with exactly one word: pong"}]},
            "route": {},
            "plan_review": {},
        }
    # Fallback: stub required fields with placeholder strings.
    return {field: "smoke" for field in _required_fields(spec)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Atelier runtime MCP tools.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually dispatch a trivial run for each tool (costs a model call)",
    )
    args = parser.parse_args()

    try:
        from atelier.core.environment import HIDDEN_LLM_TOOLS
        from atelier.gateway.adapters.mcp_server import TOOLS
        from atelier.gateway.sdk.mcp import _LoopbackTransport
    except Exception as exc:  # noqa: BLE001 - import failure is itself a smoke result
        print(f"FAIL: could not import the MCP server surface — {type(exc).__name__}: {exc}")
        return 2

    callable_by_name = sorted(TOOLS)
    hidden = sorted(t for t in callable_by_name if t in HIDDEN_LLM_TOOLS)
    print(f"callable by name ({len(callable_by_name)}): {', '.join(callable_by_name)}")
    print(f"hidden from advertised list ({len(hidden)}): {', '.join(hidden) or '(none)'}")
    print("-" * 72)

    transport = _LoopbackTransport()
    ok = True

    for name in RUNTIME_TOOLS:
        spec = TOOLS.get(name)
        if spec is None:
            print(f"[{name}] ABSENT — not registered, NOT callable by name")
            ok = False
            continue
        vis = "advertised" if name not in HIDDEN_LLM_TOOLS else "hidden (callable by name only)"
        print(f"[{name}] REGISTERED — {vis}")
        print(f"    required args: {', '.join(_required_fields(spec)) or '(none declared)'}")

        if not args.live:
            continue

        try:
            result = transport.call_tool(name, _live_args(name, spec))
            preview = str(result)
            print(f"    live dispatch: OK — {preview[:200]}{'…' if len(preview) > 200 else ''}")
        except KeyError:
            print("    live dispatch: FAIL — not callable by name (KeyError from dispatch)")
            ok = False
        except Exception as exc:  # noqa: BLE001 - any handler error is a real signal
            # Reached the handler (so it IS wired) but the run errored — surface it.
            print(f"    live dispatch: REACHED HANDLER but errored — {type(exc).__name__}: {exc}")
            ok = False

    print("-" * 72)
    if ok:
        print("RESULT: runtime tools are wired." + ("" if args.live else " (run with --live to actually execute them)"))
    else:
        print("RESULT: one or more runtime tools are missing or failed — see above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
