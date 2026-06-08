from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_KEEPALIVE_INTERVAL_SECONDS = 270  # 4.5 min — fires before 5-min TTL expiry


class KeepaliveThread:
    """Background thread that pings the LLM every ~4.5 min to keep the cache warm."""

    def __init__(self, *, model: str, interval_seconds: float = _KEEPALIVE_INTERVAL_SECONDS) -> None:
        self._model = model
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="atelier-keepalive")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._ping()
            except Exception:  # noqa: BLE001
                logger.debug("keepalive ping failed (non-fatal)", exc_info=True)

    def _ping(self) -> None:
        try:
            from atelier.infra.internal_llm.litellm_client import chat_with_result
        except Exception:  # noqa: BLE001
            return
        try:
            chat_with_result(
                [{"role": "user", "content": "ping"}],
                model=self._model,
            )
        except Exception:  # noqa: BLE001
            pass


__all__ = ["KeepaliveThread"]
