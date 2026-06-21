"""mitmproxy addon: hermetic egress allowlist for CodeBench.

Blocks any request whose host is not a model-inference endpoint, so an agent
(or a spawned subagent) cannot fetch the gold patch/test from GitHub, PyPI, etc.
SWE-bench tasks are public GitHub PRs, so open web access is effectively an
answer key — a benchmark must be hermetic for its numbers to be valid.

Allowed by default: the Anthropic API and AWS Bedrock domains (the two model
backends the benchmark authenticates against). Override with a comma-separated
CODEBENCH_EGRESS_ALLOW of domain suffixes.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mitmproxy import http

_DEFAULT_ALLOW = "anthropic.com,amazonaws.com"


def _allowed_suffixes() -> tuple[str, ...]:
    raw = os.environ.get("CODEBENCH_EGRESS_ALLOW", _DEFAULT_ALLOW)
    return tuple(s.strip().lower() for s in raw.split(",") if s.strip())


class EgressGuard:
    def __init__(self) -> None:
        self._allow = _allowed_suffixes()

    def _ok(self, host: str | None) -> bool:
        h = (host or "").lower()
        return any(h == suf or h.endswith("." + suf) for suf in self._allow)

    def _block(self):  # type: ignore[no-untyped-def]
        from mitmproxy import http

        return http.Response.make(
            403,
            b"blocked by CodeBench egress guard (hermetic benchmark)",
            {"Content-Type": "text/plain"},
        )

    def http_connect(self, flow: http.HTTPFlow) -> None:
        # HTTPS CONNECT: refuse the tunnel up-front when the host isn't allowed.
        if not self._ok(flow.request.pretty_host):
            flow.response = self._block()

    def request(self, flow: http.HTTPFlow) -> None:
        # Fallback (plain HTTP, or post-TLS request): short-circuit with 403 so
        # nothing is forwarded upstream.
        if flow.response is not None:
            return
        if not self._ok(flow.request.pretty_host):
            flow.response = self._block()


addons = [EgressGuard()]
