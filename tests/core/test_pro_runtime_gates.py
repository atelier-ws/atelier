"""Runtime entitlement gates (no CLI control surface).

These exercise gates wired into runtime/service code rather than a CLI command:
the background code-warmer's single-repo cap for Free (`unlimited_repos`).
"""

from __future__ import annotations

import base64
import json
import sys
import time
import types
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atelier.core.capabilities import pro_bridge
from atelier.core.capabilities.licensing import entitlements
from atelier.core.capabilities.optimization.policy import load_current_policy
from atelier.core.service import code_warm


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _grant(monkeypatch: pytest.MonkeyPatch, features: set[str]) -> None:
    priv = Ed25519PrivateKey.generate()
    raw_pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    payload = {
        "v": 1,
        "id": "lic",
        "email": "d@e.com",
        "plan": "pro",
        "iat": int(time.time()) - 10,
        "exp": None,
        "features": [],
    }
    seg = _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    monkeypatch.setenv("ATELIER_LICENSE_PUBLIC_KEY", base64.b64encode(raw_pub).decode("ascii"))
    monkeypatch.setenv("ATELIER_LICENSE", f"{seg}.{_b64u(priv.sign(seg.encode('ascii')))}")
    overlay = types.ModuleType("atelier_pro")
    overlay.FEATURES = frozenset(features)  # type: ignore[attr-defined]
    sys.modules["atelier_pro"] = overlay
    pro_bridge.reset_cache()
    entitlements.reload()


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    sys.modules.pop("atelier_pro", None)
    pro_bridge.reset_cache()
    monkeypatch.delenv("ATELIER_LICENSE", raising=False)
    entitlements.reload()
    yield
    sys.modules.pop("atelier_pro", None)
    pro_bridge.reset_cache()
    entitlements.reload()


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, n: int) -> None:
    workspaces = []
    for i in range(n):
        ws = tmp_path / f"ws{i}"
        ws.mkdir()
        workspaces.append(ws)
    monkeypatch.setattr(code_warm, "discover_workspaces", lambda: list(workspaces))
    # Suppress actual subprocess launches; we only count which workspaces were fired.
    monkeypatch.setattr(code_warm, "_fire_index_subprocess", lambda workspace: None)


def test_free_warms_single_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup(monkeypatch, tmp_path, 3)
    warmer = code_warm._CodeWarmer()
    warmer._warm_once()
    assert len(warmer._fired) == 1  # Free: capped to one repository


def test_pro_warms_all_repos(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup(monkeypatch, tmp_path, 3)
    _grant(monkeypatch, {"unlimited_repos"})
    warmer = code_warm._CodeWarmer()
    warmer._warm_once()
    assert len(warmer._fired) == 3  # Pro: all active workspaces


def test_free_policy_is_unoptimized(tmp_path: Path) -> None:
    # No license/overlay (autouse _clean) -> the savings engine is off.
    policy = load_current_policy(tmp_path)
    assert policy.preset == "custom"
    assert policy.compaction.trigger_at_context_fraction == 1.0


def test_pro_policy_is_balanced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _grant(monkeypatch, {"optimizer"})
    policy = load_current_policy(tmp_path)
    assert policy.preset == "balanced"


def _big_python_src() -> str:
    return "def f():\n" + "\n\n\n".join(f"    x{i} = {i}  " for i in range(2000)) + "\n"


def test_free_read_skips_source_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    from atelier.gateway.adapters import mcp_server

    monkeypatch.setenv("ATELIER_AUTO_COMPACT_OUTPUT", "1")
    monkeypatch.setenv("ATELIER_MCP_COMPACT_RESULT_CHARS", "2000")
    out = mcp_server._auto_compact_result_text(_big_python_src(), "read", {"path": "mod.py"})
    assert "source_projection" not in out  # Free: AST projection gated off


def test_pro_read_uses_source_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    _grant(monkeypatch, {"source_projection"})
    from atelier.gateway.adapters import mcp_server

    monkeypatch.setenv("ATELIER_AUTO_COMPACT_OUTPUT", "1")
    monkeypatch.setenv("ATELIER_MCP_COMPACT_RESULT_CHARS", "2000")
    out = mcp_server._auto_compact_result_text(_big_python_src(), "read", {"path": "mod.py"})
    assert "source_projection:python" in out  # Pro: AST projection applies
