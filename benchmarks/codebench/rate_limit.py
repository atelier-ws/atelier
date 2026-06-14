"""mitmproxy addon for limiting model inference requests during CodeBench."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mitmproxy import http


def _is_model_request(flow: http.HTTPFlow) -> bool:
    path = flow.request.path.lower()
    return (
        "/invoke" in path
        or path.endswith("/messages")
        or path.endswith("/chat/completions")
        or path.endswith("/responses")
    )


class ModelRequestRateLimiter:
    def __init__(self) -> None:
        rpm = float(os.environ.get("CODEBENCH_RATE_LIMIT_RPM", "0") or 0)
        self._interval = 60.0 / rpm if rpm > 0 else 0.0
        self._tokens_per_minute = int(os.environ.get("CODEBENCH_RATE_LIMIT_TPM", "0") or 0)
        self._lock = asyncio.Lock()
        self._next_request_at = 0.0
        self._token_reservations: deque[tuple[float, int]] = deque()

    @staticmethod
    def _reserved_output_tokens(flow: http.HTTPFlow) -> int:
        try:
            payload = json.loads(flow.request.get_text(strict=False))
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0
        return max(int(payload.get("max_tokens", 0) or 0), 0)

    def _token_delay(self, now: float, reservation: int) -> float:
        while self._token_reservations and now - self._token_reservations[0][0] >= 60:
            self._token_reservations.popleft()
        if self._tokens_per_minute <= 0 or reservation <= 0:
            return 0.0
        used = sum(tokens for _, tokens in self._token_reservations)
        if used + reservation <= self._tokens_per_minute:
            return 0.0
        return max(60 - (now - self._token_reservations[0][0]), 0.0)

    async def request(self, flow: http.HTTPFlow) -> None:
        if not _is_model_request(flow):
            return
        reservation = self._reserved_output_tokens(flow)
        async with self._lock:
            while True:
                now = time.monotonic()
                delay = max(
                    self._next_request_at - now,
                    self._token_delay(now, reservation),
                )
                if delay <= 0:
                    break
                await asyncio.sleep(delay)
            admitted_at = time.monotonic()
            self._next_request_at = admitted_at + self._interval
            if self._tokens_per_minute > 0 and reservation > 0:
                self._token_reservations.append((admitted_at, reservation))
        # Bedrock event streams can stall when mitmproxy reuses an HTTP/1.1
        # upstream connection after a prior streamed response.
        flow.request.headers["Connection"] = "close"


addons = [ModelRequestRateLimiter()]
