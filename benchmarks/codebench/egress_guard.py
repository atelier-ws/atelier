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


def _max_requests() -> int:
    """Opt-in runaway ceiling: max model-inference requests per job. 0 disables it."""
    try:
        cap = int(os.environ.get("CODEBENCH_MAX_REQUESTS", "0"))
    except ValueError:
        return 0
    return cap if cap > 0 else 0


class EgressGuard:
    def __init__(self) -> None:
        self._allow = _allowed_suffixes()
        self._max_requests = _max_requests()
        self._model_requests = 0

    def _ok(self, host: str | None) -> bool:
        h = (host or "").lower()
        return any(h == suf or h.endswith("." + suf) for suf in self._allow)

    def _block(self, body: bytes = b"blocked by CodeBench egress guard (hermetic benchmark)"):  # type: ignore[no-untyped-def]
        from mitmproxy import http

        return http.Response.make(
            403,
            body,
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
            return
        # Opt-in runaway backstop: a job's parent agent and every subagent it
        # spawns all route through this one proxy, so a per-process counter
        # bounds the whole agent tree (the per-agent turn cap does not). Only
        # model-inference calls count; 0 = disabled, so this is a no-op unless
        # CODEBENCH_MAX_REQUESTS is set.
        if self._max_requests and "/v1/messages" in flow.request.path:
            self._model_requests += 1
            if self._model_requests > self._max_requests:
                flow.response = self._block(
                    f"blocked by CodeBench runaway ceiling (>{self._max_requests} model requests)".encode()
                )


addons = [EgressGuard()]
