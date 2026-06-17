"""Service for watching and ingesting session directories."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from atelier.core.foundation.paths import default_store_root
from atelier.core.service.ingest_session import ingest_session_file
from atelier.infra.storage.factory import make_memory_store

logger = logging.getLogger(__name__)


class SessionDirectoryWatcher:
    """Watches a directory for new or modified session files and ingests them."""

    def __init__(self, directory_path: str, store: Any = None, poll_interval: float = 5.0):
        self.directory_path = directory_path
        self.store = store
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._seen_files: dict[Path, tuple[float, int]] = {}

        if self.store is None:
            store_root = default_store_root()
            self.store = make_memory_store(store_root)

        self.directory = Path(directory_path)
        if not self.directory.exists() or not self.directory.is_dir():
            raise ValueError(f"Directory does not exist or is not a directory: {directory_path}")

    def start(self) -> None:
        """Start the directory watcher in a background thread."""
        if self._worker is not None and self._worker.is_alive():
            logger.warning("Directory watcher is already running")
            return

        self._stop_event.clear()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()
        logger.info(
            "Started directory watcher for: %s (poll interval: %ss)",
            self.directory_path,
            self.poll_interval,
        )

    def stop(self) -> None:
        """Stop the directory watcher."""
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=10.0)
            self._worker = None
        logger.info("Stopped directory watcher for: %s", self.directory_path)

    def _run(self) -> None:
        """Main watcher loop."""
        logger.info("Directory watcher loop started for: %s", self.directory_path)

        try:
            while not self._stop_event.is_set():
                try:
                    # Scan for .jsonl files in the directory
                    for file_path in self.directory.glob("*.jsonl"):
                        try:
                            stat = file_path.stat()
                            signature = (stat.st_mtime, stat.st_size)
                            # If we haven't seen this file or its (mtime, size) changed.
                            # Comparing size as well as mtime catches same-second
                            # rewrites that coarse mtime granularity would miss.
                            if self._seen_files.get(file_path) != signature:
                                logger.info("Detected new or modified session file: %s", file_path)
                                result = ingest_session_file(str(file_path), self.store)
                                if result.get("status") == "success":
                                    logger.info(
                                        "Successfully ingested session file: %s (session_id: %s, events: %d)",
                                        file_path,
                                        result.get("session_id"),
                                        result.get("event_count", 0),
                                    )
                                else:
                                    logger.error(
                                        "Failed to ingest session file %s: %s",
                                        file_path,
                                        result.get("message", "Unknown error"),
                                    )
                                # Re-stat after ingest so a write that landed mid-ingest
                                # produces a different signature and is re-detected next poll.
                                post = file_path.stat()
                                self._seen_files[file_path] = (post.st_mtime, post.st_size)
                        except OSError as exc:
                            logger.error("Error accessing file %s: %s", file_path, exc)

                    # Remove entries for files that no longer exist
                    self._seen_files = {path: sig for path, sig in self._seen_files.items() if path.exists()}

                    # Wait for the next poll interval or until stopped
                    self._stop_event.wait(self.poll_interval)
                except Exception as exc:  # pylint: disable=broad-except
                    logging.exception("Recovered from broad exception handler")
                    logger.error("Unexpected error in directory watcher loop: %s", exc)
                    time.sleep(self.poll_interval)  # Wait before retrying
        except Exception as exc:  # pylint: disable=broad-except
            logging.exception("Recovered from broad exception handler")
            logger.error("Directory watcher failed: %s", exc)
        finally:
            logger.info("Directory watcher loop ended for: %s", self.directory_path)


def ingest_session_directory(directory_path: str, store: Any = None, poll_interval: float = 5.0) -> dict[str, Any]:
    """Start watching a directory for new or modified session files and ingest them.

    This function returns immediately after starting the watcher in a background thread.

    Args:
        directory_path: Path to the directory to watch for session files.
        store: Optional store instance. If not provided, the default store is used.
        poll_interval: Seconds to wait between directory scans.

    Returns:
        A dictionary with the result of starting the watcher.
    """
    try:
        watcher = SessionDirectoryWatcher(directory_path, store, poll_interval)
        watcher.start()
        return {
            "status": "success",
            "message": f"Directory watcher started for {directory_path}",
            "watcher": watcher,  # Return the watcher so caller can stop it later if needed
        }
    except Exception as exc:  # pylint: disable=broad-except
        logging.exception("Recovered from broad exception handler")
        logger.error("Failed to start directory watcher: %s", exc)
        return {
            "status": "error",
            "message": f"Failed to start directory watcher: {exc}",
        }


def ingest_session_directory_blocking(directory_path: str, store: Any = None, poll_interval: float = 5.0) -> None:
    """Watch a directory for new or modified session files and ingest them (blocking).

    This function runs indefinitely, polling the directory at the specified interval.
    Intended for use in a dedicated worker process.

    Args:
        directory_path: Path to the directory to watch for session files.
        store: Optional store instance. If not provided, the default store is used.
        poll_interval: Seconds to wait between directory scans.
    """
    watcher = SessionDirectoryWatcher(directory_path, store, poll_interval)
    try:
        watcher.start()
        # Wait forever until interrupted
        while not watcher._stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Directory watcher stopped by user")
    finally:
        watcher.stop()
