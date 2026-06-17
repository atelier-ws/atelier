"""Shared fixtures for gateway / MCP-surface tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _disable_code_autosync() -> None:
    """Disable autosync for gateway tests to make them deterministic.

    MCP transport engines are constructed with ``nonblocking_reads=True``: a cold
    read returns immediately and lets the background autosync worker build the
    index. That background build races the assertions and makes MCP-surface
    tests non-deterministic. With autosync disabled there is no worker, so a cold
    read falls back to a synchronous build and the test observes a fully built
    index deterministically. The non-blocking read path itself is covered by
    tests/core/test_code_context.py::test_nonblocking_reads_skip_cold_build_while_default_blocks.
    """
    from atelier.core.capabilities.code_context import CodeContextEngine

    original_init = CodeContextEngine.__init__

    def patched_init(self, repo_root, *, db_path=None, nonblocking_reads=False, autosync_enabled=None):
        # Force autosync_enabled=False for deterministic tests
        original_init(self, repo_root, db_path=db_path, nonblocking_reads=nonblocking_reads, autosync_enabled=False)

    with patch.object(CodeContextEngine, "__init__", patched_init):
        yield
