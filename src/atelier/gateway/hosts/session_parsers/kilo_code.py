"""KiloCode session importer for Atelier."""

from __future__ import annotations

import logging
from pathlib import Path

from atelier.core.foundation.store import ContextStore
from atelier.gateway.hosts.session_parsers._common import get_newest
from atelier.gateway.hosts.session_parsers._vscode_cline import find_task_dirs, import_task_dir

logger = logging.getLogger(__name__)

_EXTENSION_ID = "kilocode.kilo-code"


def find_kilo_code_sessions(root: Path | None = None) -> list[Path]:
    return find_task_dirs(_EXTENSION_ID, root)


class KiloCodeImporter:
    def __init__(self, store: ContextStore) -> None:
        self.store = store

    def import_all(self, root: Path | None = None, *, force: bool = False, limit: int | None = None) -> list[str]:
        imported: list[str] = []
        task_dirs = get_newest(find_kilo_code_sessions(root), limit)
        total = len(task_dirs)
        logger.info(
            "[atelier] kilo-code: discovering tasks (found %d, processing top %s)",
            total,
            limit if limit is not None else "all",
        )
        for i, task_dir in enumerate(task_dirs):
            if i % 10 == 0 and i > 0:
                logger.info("[atelier] kilo-code: importing %d/%d...", i, total)
            trace_id = import_task_dir(
                self.store,
                host="kilo-code",
                extension_id=_EXTENSION_ID,
                task_dir=task_dir,
                force=force,
            )
            if trace_id:
                imported.append(trace_id)
        return imported
