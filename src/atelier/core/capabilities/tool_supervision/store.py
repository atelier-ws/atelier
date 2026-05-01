"""Atomic JSON store with history rotation for tool supervision state."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

_STORE_FILENAME = "tool_supervision.json"
_MAX_HISTORY = 200


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".~sup_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class SupervisionStore:
    """Persistent JSON store for tool supervision cache and history."""

    def __init__(self, root: Path) -> None:
        self._path = Path(root) / _STORE_FILENAME

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"cache": {}, "history": []}
        try:
            import typing

            return typing.cast(dict[str, Any], json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return {"cache": {}, "history": []}

    def save(self, state: dict[str, Any]) -> None:
        # Rotate history
        history = state.get("history", [])
        if len(history) > _MAX_HISTORY:
            state["history"] = history[-_MAX_HISTORY:]
        _atomic_write(self._path, json.dumps(state, indent=2))

    def get_cached(self, key: str) -> dict[str, Any] | None:
        state = self.load()
        import typing

        return typing.cast(dict[str, Any] | None, state.get("cache", {}).get(key))

    def set_cached(self, key: str, payload: dict[str, Any]) -> None:
        state = self.load()
        state.setdefault("cache", {})[key] = payload
        self.save(state)

    def append_history(self, entry: dict[str, Any]) -> None:
        state = self.load()
        state.setdefault("history", []).append(entry)
        self.save(state)
