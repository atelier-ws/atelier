"""mitmproxy addon for limiting model inference requests during AtelierBench."""

from __future__ import annotations

import os
import threading
import time

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
        rpm = float(os.environ.get("ATELIERBENCH_RATE_LIMIT_RPM", "0") or 0)
        self._interval = 60.0 / rpm if rpm > 0 else 0.0
        self._lock = threading.Lock()
        self._next_request_at = 0.0

    def request(self, flow: http.HTTPFlow) -> None:
        if self._interval <= 0 or not _is_model_request(flow):
            return
        with self._lock:
            now = time.monotonic()
            delay = self._next_request_at - now
            if delay > 0:
                time.sleep(delay)
            self._next_request_at = time.monotonic() + self._interval


addons = [ModelRequestRateLimiter()]
