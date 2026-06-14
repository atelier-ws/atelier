"""Shared fixtures for gateway / MCP-surface tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_code_autosync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the code-index autosync worker for gateway tests.

    MCP transport engines are constructed with ``nonblocking_reads=True``: a cold
    read returns immediately and lets the background autosync worker build the
    index. That background build races the assertions and makes MCP-surface
    tests non-deterministic. With autosync disabled there is no worker, so a cold
    read falls back to a synchronous build and the test observes a fully built
    index deterministically. The non-blocking read path itself is covered by
    tests/core/test_code_context.py::test_nonblocking_reads_skip_cold_build_while_default_blocks.
    """
    monkeypatch.setenv("ATELIER_CODE_AUTOSYNC", "0")
