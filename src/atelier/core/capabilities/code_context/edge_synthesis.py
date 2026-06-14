"""Bounded, provenance-tagged call-edge synthesis (N2/N3 -- first iteration).

The full dynamic-dispatch + 20+ framework-resolver subsystem is explicitly out
of scope for one pass. This module does the *additive, separable* minimum:

* It recognises a SMALL, fixed set of common indirection patterns and emits
  synthesized edges for them.
* Every edge is tagged ``provenance="heuristic"`` (mirroring the cross_lang
  edge confidence/kind convention) so it is never confused with a static SCIP
  edge.
* It writes NOTHING into ``call_edges`` and is never folded into
  ``callers``/``callees`` traversal. Callers request synthesized edges
  explicitly; default behaviour of every existing tool is byte-for-byte
  unchanged.

Patterns covered in this iteration (deliberately two, one per ecosystem):

1. Flask route -> handler: ``@app.route("/path")`` (or ``@bp.route``) directly
   above a ``def handler(...)`` synthesizes ``route:/path -> handler``.
2. JS/TS EventEmitter -> handler: ``emitter.on("event", handlerName)``
   synthesizes ``on:event -> handlerName`` when the handler is a bare
   identifier (not an inline lambda, which has no name to point at).

Anything outside these two patterns is intentionally NOT synthesized; a partial
that never lies is better than a broad one that fabricates edges.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

SynthesizedEdgeKind = Literal["flask_route", "event_handler"]

# Bare-identifier handler in `emitter.on('evt', handlerName)`. Inline functions
# (`function (){}` / `() => {}`) are skipped on purpose -- no nameable target.
_JS_ON_RE = re.compile(r"""\.on\(\s*['"](?P<event>[^'"]+)['"]\s*,\s*(?P<handler>[A-Za-z_$][\w$]*)\s*\)""")


@dataclass(frozen=True)
class SynthesizedEdge:
    """A heuristically-inferred caller->callee edge, clearly labelled as such."""

    caller: str
    callee: str
    kind: SynthesizedEdgeKind
    line: int
    provenance: str = "heuristic"
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "callee": self.callee,
            "kind": self.kind,
            "line": self.line,
            "provenance": self.provenance,
            "confidence": self.confidence,
        }


def synthesize_edges(source: str, *, language: str) -> list[SynthesizedEdge]:
    """Return synthesized edges for *source*. Empty list on parse failure.

    Pure and side-effect free. ``language`` selects the resolver; unknown
    languages yield no edges.
    """
    if language == "python":
        return _synthesize_flask_routes(source)
    if language in ("javascript", "typescript"):
        return _synthesize_event_handlers(source)
    return []


def _synthesize_flask_routes(source: str) -> list[SynthesizedEdge]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    edges: list[SynthesizedEdge] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            route = _route_path_from_decorator(dec)
            if route is None:
                continue
            edges.append(
                SynthesizedEdge(
                    caller=f"route:{route}",
                    callee=node.name,
                    kind="flask_route",
                    line=node.lineno,
                )
            )
    edges.sort(key=lambda e: (e.line, e.callee))
    return edges


def _route_path_from_decorator(dec: ast.expr) -> str | None:
    """Return the route path if *dec* is an ``X.route("/path", ...)`` call."""
    if not isinstance(dec, ast.Call):
        return None
    func = dec.func
    if not isinstance(func, ast.Attribute) or func.attr != "route":
        return None
    if not dec.args:
        return None
    first = dec.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _synthesize_event_handlers(source: str) -> list[SynthesizedEdge]:
    edges: list[SynthesizedEdge] = []
    try:
        for match in _JS_ON_RE.finditer(source):
            event = match.group("event")
            handler = match.group("handler")
            line = source.count("\n", 0, match.start()) + 1
            edges.append(
                SynthesizedEdge(
                    caller=f"on:{event}",
                    callee=handler,
                    kind="event_handler",
                    line=line,
                )
            )
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return []
    edges.sort(key=lambda e: (e.line, e.callee))
    return edges
