"""Tests for the consolidated MCP contract."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from atelier.core.capabilities.code_context import CodeContextEngine
from atelier.core.environment import HIDDEN_LLM_TOOLS
from atelier.core.service.bootstrap_context import build_bootstrap_plan, persist_bootstrap_plan
from atelier.core.service.jobs import JOB_BOOTSTRAP_CONTEXT
from atelier.gateway.adapters import mcp_server
from atelier.gateway.adapters.mcp_server import TOOLS, _handle, tool_smart_edit
from atelier.gateway.cli import cli
from atelier.infra.code_intel.astgrep import (
    AstGrepToolUnavailable,
    PatternMatch,
    PatternRewriteResult,
    PatternSearchResult,
)
from atelier.infra.code_intel.scip.indexer import ScipIndexer
from atelier.infra.storage.factory import create_store, make_memory_store
from tests.helpers import init_store_at

EXPECTED_TOOLS = {
    "memory",
    "read",
    "edit",
    "grep",
    "sql",
    "search",
    "shell",
    "web_fetch",
    # Dedicated code-intel tools (split from `code` op for LLM discoverability)
    "node",
    "callers",
    "callees",
    "usages",
    "explore",
    "codemod",
}


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    req: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    resp = _handle(req)
    assert isinstance(resp, dict)
    return resp


def _result(resp: dict[str, Any]) -> Any:
    assert "result" in resp, resp
    text = resp["result"]["content"][0]["text"]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _op_result(render_name: str, op_fn: Any, **kwargs: Any) -> Any:
    """Mirror _handle's render path for a direct _op_* call: returns rendered
    markdown when a code renderer applies, else the raw payload dict."""
    mcp_server._tool_call_rendered_text.value = None
    payload = op_fn(**kwargs)
    rendered = mcp_server.render_tool_result_text(render_name, payload)
    return rendered if rendered is not None else payload


def _mock_client(return_values: dict[str, dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    for method_name, retval in return_values.items():
        getattr(client, method_name).return_value = retval
    return client


def _write_gateway_scip_fixture(
    repo_root: Path,
    *,
    symbol_id: str,
    include_call_graph: bool = False,
    artifact_name: str = "python.scip",
    file_path: str = "a.py",
    symbol_name: str = "alpha",
    qualified_name: str = "alpha",
    source: str | None = None,
) -> Path:
    engine = CodeContextEngine(repo_root)
    symbol_source = source or (repo_root / file_path).read_text(encoding="utf-8")
    caller_source = (repo_root / "b.py").read_text(encoding="utf-8") if (repo_root / "b.py").exists() else ""
    artifact_dir = ScipIndexer(repo_root, engine.repo_id).cache_root
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path: Path = artifact_dir / artifact_name
    payload: dict[str, Any] = {
        "version": 1,
        "repo_id": engine.repo_id,
        "language": "python",
        "index_sha": "a" * 40,
        "symbols": [
            {
                "symbol_id": symbol_id,
                "repo_id": engine.repo_id,
                "file_path": file_path,
                "language": "python",
                "symbol_name": symbol_name,
                "qualified_name": qualified_name,
                "kind": "function",
                "signature": f"def {symbol_name}():",
                "start_byte": 0,
                "end_byte": len(symbol_source.encode("utf-8")),
                "start_line": 1,
                "end_line": len(symbol_source.splitlines()),
                "content_hash": hashlib.sha256(symbol_source.encode("utf-8")).hexdigest(),
                "source": symbol_source,
                "provenance": "scip",
            }
        ],
    }
    if include_call_graph:
        payload["symbols"].append(
            {
                "symbol_id": "scip-beta",
                "repo_id": engine.repo_id,
                "file_path": "b.py",
                "language": "python",
                "symbol_name": "beta",
                "qualified_name": "beta",
                "kind": "function",
                "signature": "def beta():",
                "start_byte": 0,
                "end_byte": len(caller_source.encode("utf-8")),
                "start_line": 3,
                "end_line": 4,
                "content_hash": hashlib.sha256(caller_source.encode("utf-8")).hexdigest(),
                "source": caller_source,
                "provenance": "scip",
            }
        )
        payload["call_graph"] = {
            "callers": {
                symbol_id: [
                    {
                        "symbol_id": "scip-beta",
                        "symbol_name": "beta",
                        "qualified_name": "beta",
                        "file_path": "b.py",
                        "kind": "function",
                        "start_line": 3,
                        "end_line": 4,
                        "provenance": "scip",
                    }
                ]
            },
            "callees": {
                "scip-beta": [
                    {
                        "symbol_id": symbol_id,
                        "symbol_name": "alpha",
                        "qualified_name": "alpha",
                        "file_path": "a.py",
                        "kind": "function",
                        "start_line": 1,
                        "end_line": 2,
                        "provenance": "scip",
                    }
                ]
            },
        }
    artifact_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return artifact_path


def _write_bootstrap_fixture_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "app.py").write_text(
        "from src.worker import run_worker\n\ndef main() -> str:\n    return run_worker()\n",
        encoding="utf-8",
    )
    (root / "src" / "worker.py").write_text(
        "def run_worker() -> str:\n    return 'ready'\n",
        encoding="utf-8",
    )
    (root / "scripts" / "cli.py").write_text(
        "from src.app import main\n\ndef cli() -> str:\n    return main()\n",
        encoding="utf-8",
    )


def _write_workspace_fixture_repo(root: Path, *, module_name: str, class_name: str = "SharedConfig") -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "config.py").write_text(
        f"class {class_name}:\n    SOURCE = '{module_name}'\n",
        encoding="utf-8",
    )


def _write_workspace_fixture_config(workspace_root: Path, sibling_root: Path) -> None:
    (workspace_root / ".atelier").mkdir(parents=True, exist_ok=True)
    (workspace_root / ".atelier" / "workspace.toml").write_text(
        "\n".join(
            [
                "[workspace]",
                'id = "fixture-workspace"',
                "",
                "[[workspace.repos]]",
                'name = "atelier"',
                'path = "."',
                "",
                "[[workspace.repos]]",
                'name = "billing"',
                f'path = "{os.path.relpath(sibling_root, workspace_root)}"',
                "",
            ]
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def store_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".atelier"
    init_store_at(str(root))
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("ATELIER_MEMORY_BACKEND", "sqlite")
    # Trace persistence tests exercise the local ledger path; an ambient
    # ATELIER_SERVICE_URL would force remote dispatch and skip _current_ledger.
    monkeypatch.delenv("ATELIER_SERVICE_URL", raising=False)
    mcp_server._current_ledger = None
    mcp_server._realtime_ctx = None
    mcp_server._remote_client = _mock_client(
        {
            "get_context": {"context": "Here are the relevant procedures.", "run_ledger": []},
            "rescue_failure": {
                "rescue": "Try a narrower reproduction.",
                "analysis": "repeat failure",
            },
            "record_trace": {"id": "trace-123", "event_recorded": True},
            "run_rubric_gate": {"status": "pass"},
        }
    )
    return root


def test_initialize_returns_server_info() -> None:
    resp = _handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
        }
    )
    assert resp is not None
    assert resp["result"]["serverInfo"]["name"] == "atelier-context"
    assert resp["result"]["protocolVersion"] == "2024-11-05"


def test_notifications_initialized_returns_none() -> None:
    resp = _handle({"jsonrpc": "2.0", "id": None, "method": "notifications/initialized", "params": {}})
    assert resp is None


def test_tools_list_returns_exact_public_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert resp is not None
    names = {tool["name"] for tool in resp["result"]["tools"]}
    assert names == EXPECTED_TOOLS
    assert EXPECTED_TOOLS | HIDDEN_LLM_TOOLS == set(TOOLS)


def test_tools_list_hides_internal_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert resp is not None
    tools = resp["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert names == EXPECTED_TOOLS
    assert not (names & HIDDEN_LLM_TOOLS)
    assert "read" in names
    assert all("passive" not in tool["description"] for tool in tools if tool["name"] in EXPECTED_TOOLS)


def test_memory_tool_call_works_without_dev_mode(store_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = store_root
    monkeypatch.delenv("ATELIER_SERVICE_URL", raising=False)
    mcp_server._remote_client = None
    resp = _call(
        "memory",
        {
            "op": "store_fact",
            "agent_id": "atelier:non-dev",
            "subject": "test",
            "fact": "Memory should be active in non-dev mode.",
            "citations": 'Test: "direct"',
            "reason": "Verifying non-dev memory works.",
            "scope": "user",
        },
    )
    payload = _result(resp)
    assert payload["fact"] == "Memory should be active in non-dev mode."

    recalled = _result(
        _call(
            "memory",
            {
                "op": "recall",
                "query": "Memory should be active in non-dev mode.",
            },
        )
    )
    assert "passages" in recalled


def test_cli_tools_list_hides_internal_tools_even_with_legacy_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()

    stable = runner.invoke(cli, ["--root", str(tmp_path / ".atelier"), "tools", "list"])
    assert stable.exit_code == 0, stable.output
    assert set(stable.output.splitlines()) == EXPECTED_TOOLS

    dev = runner.invoke(cli, ["--root", str(tmp_path / ".atelier"), "tools", "list", "--dev"])
    assert dev.exit_code == 0, dev.output
    assert set(dev.output.splitlines()) == EXPECTED_TOOLS


def test_cli_tools_call_invokes_stable_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "--root",
            str(tmp_path / ".atelier"),
            "tools",
            "call",
            "compact",
            "--args",
            "{}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "tokens_freed" in payload


def test_tools_list_each_entry_has_schema() -> None:
    resp = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert resp is not None
    for tool in resp["result"]["tools"]:
        assert tool["name"]
        assert isinstance(tool.get("inputSchema"), dict)


def test_tools_list_search_schema_prefers_path_and_documents_modes() -> None:
    search_tool = TOOLS["search"]
    properties = search_tool["inputSchema"]["properties"]

    assert "query" in search_tool["description"]
    assert "path" in properties
    assert "file_path" not in properties
    assert "content_regex" not in properties
    assert properties["path"]["description"].startswith("Workspace-relative file or directory to search.")
    assert "#start-end" in properties["path"]["description"]
    assert "repo map" in properties["mode"]["description"].lower()


def test_tools_list_grep_schema_covers_native_mode() -> None:
    grep_tool = TOOLS["grep"]
    properties = grep_tool["inputSchema"]["properties"]

    assert "regex" in grep_tool["description"].lower()
    assert "path" in properties
    assert "file_path" not in properties
    assert "content_regex" in properties
    assert "summary" in properties


def test_tools_list_edit_schema_documents_descriptor_variants() -> None:
    edit_tool = TOOLS["edit"]
    schema = edit_tool["inputSchema"]
    edits_schema = schema["properties"]["edits"]
    variants = edits_schema["items"]["anyOf"]

    assert schema["required"] == ["edits"]
    assert len(variants) == 4
    assert {variant["title"] for variant in variants} == {
        "File edit",
        "Notebook cell edit",
        "Symbol edit",
        "Projection edit",
    }
    symbol_variant = next(v for v in variants if v["title"] == "Symbol edit")
    assert "symbol_id" not in symbol_variant["properties"]
    assert "symbol_name" not in symbol_variant["properties"]
    projection_variant = next(v for v in variants if v["title"] == "Projection edit")
    assert "projection_mapping" in projection_variant["properties"]
    assert "projected_ranges" in projection_variant["properties"]
    assert "description" not in edits_schema


def test_tools_list_memory_schema_describes_ops_and_required_fields() -> None:
    memory_tool = TOOLS["memory"]
    properties = memory_tool["inputSchema"]["properties"]

    assert "fact storage/voting and recall" in memory_tool["description"]
    assert "store_fact" in properties["op"]["description"]
    assert "vote_fact" in properties["op"]["description"]
    assert "recall requires query" in properties["op"]["description"]
    assert "query used by recall" in properties["query"]["description"].lower()
    assert "subject" in properties
    assert "fact" in properties
    assert "citations" in properties
    assert "direction" in properties
    assert "label" not in properties
    assert "session_id" not in properties
    assert "expected_version" not in properties


def test_unknown_method_returns_error() -> None:
    resp = _handle({"jsonrpc": "2.0", "id": 3, "method": "unknown/method", "params": {}})
    assert resp is not None
    assert resp["error"]["code"] == -32601


def test_unknown_tool_returns_error() -> None:
    resp = _call("does_not_exist", {})
    assert "error" in resp
    assert "unknown tool" in resp["error"]["message"]


def test_get_context_can_include_folded_state(store_root: Path) -> None:
    resp = _call(
        "context",
        {"task": "Fix publish regression", "include_run_ledger": True},
    )
    payload = _result(resp)
    assert isinstance(payload.get("context"), str)
    assert "run_ledger" in payload


@pytest.mark.slow
def test_context_enqueues_single_bootstrap_job_for_cold_repo(
    store_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = Path(os.environ["CLAUDE_WORKSPACE_ROOT"])
    _write_bootstrap_fixture_repo(workspace_root)
    mcp_server._reset_runtime_cache_for_testing()
    monkeypatch.setattr(mcp_server, "_run_worker_tick_safe", lambda root: None)

    first = mcp_server.tool_get_context({"task": "Map the repo entry points"})
    second = mcp_server.tool_get_context({"task": "Map the repo entry points"})

    store = create_store(store_root)
    store.init()
    jobs = [
        job
        for job in store.list_jobs(job_type=JOB_BOOTSTRAP_CONTEXT, limit=20)
        if job["status"] in {"pending", "running"}
    ]

    assert len(jobs) == 1
    assert first["bootstrap"]["queued"] is True
    assert second["bootstrap"]["queued"] is False


def test_context_worker_tick_persists_bootstrap_blocks_without_blocking_initial_response(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATELIER_DEV_MODE", "1")
    workspace_root = Path(os.environ["CLAUDE_WORKSPACE_ROOT"])
    monkeypatch.delenv("ATELIER_SERVICE_URL", raising=False)
    mcp_server._remote_client = None
    _write_bootstrap_fixture_repo(workspace_root)
    mcp_server._reset_runtime_cache_for_testing()

    payload = mcp_server.tool_get_context({"task": "Warm the repository context"})

    assert "Repository bootstrap" not in payload["context"]
    mcp_server._run_worker_tick_safe(store_root)

    plan = build_bootstrap_plan(workspace_root)
    bootstrap_count = 0
    for _ in range(3):
        blocks = make_memory_store(store_root).list_pinned_blocks(plan.agent_id)
        bootstrap_count = len([block for block in blocks if block.label.startswith(f"bootstrap/{plan.repo_id}/")])
        if bootstrap_count == 4:
            break
        mcp_server._run_worker_tick_safe(store_root)

    assert bootstrap_count == 4


def test_context_reuses_bootstrap_blocks_instead_of_enqueuing_duplicate_work(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = Path(os.environ["CLAUDE_WORKSPACE_ROOT"])
    monkeypatch.delenv("ATELIER_SERVICE_URL", raising=False)
    mcp_server._remote_client = None
    _write_bootstrap_fixture_repo(workspace_root)
    mcp_server._reset_runtime_cache_for_testing()

    mcp_server.tool_get_context({"task": "Warm the repository context"})
    mcp_server._run_worker_tick_safe(store_root)
    mcp_server._reset_runtime_cache_for_testing()
    payload = mcp_server.tool_get_context({"task": "Warm the repository context"})

    store = create_store(store_root)
    store.init()
    jobs = store.list_jobs(job_type=JOB_BOOTSTRAP_CONTEXT, limit=20)

    assert len(jobs) == 1
    assert payload["bootstrap"]["status"] in {"warm", "warming"}
    if payload["bootstrap"]["status"] == "warm":
        assert "Repository bootstrap" in payload["context"]


def test_context_injects_preseeded_bootstrap_blocks_without_recomputing(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = Path(os.environ["CLAUDE_WORKSPACE_ROOT"])
    monkeypatch.delenv("ATELIER_SERVICE_URL", raising=False)
    mcp_server._remote_client = None
    _write_bootstrap_fixture_repo(workspace_root)
    memory_store = make_memory_store(store_root)
    persist_bootstrap_plan(workspace_root, memory_store)
    mcp_server._reset_runtime_cache_for_testing()

    payload = mcp_server.tool_get_context({"task": "Use the warmed bootstrap state"})

    store = create_store(store_root)
    store.init()
    assert store.list_jobs(job_type=JOB_BOOTSTRAP_CONTEXT, limit=20) == []
    assert payload["bootstrap"]["status"] == "warm"
    assert "architecture-sketch" in payload["context"]


def test_context_pull_threads_keywords_and_excluded_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_pull(self: Any, subtask: Any) -> Any:
        seen["subtask"] = subtask
        from atelier.core.capabilities.scoped_context import ScopedContext

        return ScopedContext(
            chunks=[],
            rationale="ok",
            excluded=[],
            trace_id="trace",
            total_tokens=0,
            dropped_for_budget=0,
        )

    monkeypatch.setattr(mcp_server, "_code_context_engine", lambda root: object())
    monkeypatch.setattr(
        "atelier.core.capabilities.scoped_context.ScopedContextCapability.pull",
        fake_pull,
    )

    payload = mcp_server.tool_get_context(
        {
            "task": "fix auth flow",
            "mode": "pull",
            "files": ["src/auth.py"],
            "keywords": ["auth", "login"],
            "excluded_paths": ["src/legacy"],
            "token_budget": 321,
        }
    )

    subtask = seen["subtask"]
    assert subtask.description == "fix auth flow"
    assert subtask.affected_paths == ["src/auth.py"]
    assert subtask.keywords == ["auth", "login"]
    assert subtask.excluded_paths == ["src/legacy"]
    assert subtask.budget_tokens == 321
    assert payload["rationale"] == "ok"


def test_context_pull_reuses_cached_scoped_context(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakePullRecord:
        def __init__(self, file_path: str, symbol_name: str) -> None:
            self.file_path = file_path
            self.symbol_name = symbol_name
            self.kind = "function"
            self.language = "python"
            self.qualified_name = symbol_name
            self.signature = f"def {symbol_name}(): ..."
            self.snippet = "return 1"
            self.score = 0.9

    class _FakePullEngine:
        def __init__(self) -> None:
            self.index_version = 0

        def _current_index_version(self) -> int:
            return self.index_version

        def search_symbols(
            self,
            query: str,
            *,
            limit: int = 20,
            mode: str = "auto",
            snippet: str = "head",
            file_glob: str | None = None,
            **_: object,
        ) -> list[_FakePullRecord]:
            ignored = (query, limit, mode, snippet)
            assert ignored
            records = [_FakePullRecord("src/auth.py", "auth_flow")]
            if file_glob is None:
                return records
            return [record for record in records if record.file_path == file_glob]

    mcp_server._reset_runtime_cache_for_testing()
    monkeypatch.setattr(mcp_server, "_code_context_engine", lambda repo_root=".": _FakePullEngine())

    first = mcp_server.tool_get_context(
        {"task": "fix auth flow", "mode": "pull", "files": ["src/auth.py"], "token_budget": 400}
    )
    second = mcp_server.tool_get_context(
        {"task": "fix auth flow", "mode": "pull", "files": ["src/auth.py"], "token_budget": 400}
    )

    assert first["provenance"] == "fresh"
    assert second["provenance"] == "cached"


def test_rescue_failure_returns_procedure(store_root: Path) -> None:
    _ = store_root
    payload = _result(
        _call(
            "rescue",
            {
                "task": "Run tests",
                "error": "pytest AssertionError",
                "recent_actions": ["run pytest", "run pytest"],
            },
        )
    )
    assert "rescue" in payload
    assert "analysis" in payload


def test_record_trace_accepts_monitor_event_payload(store_root: Path) -> None:
    _ = store_root
    payload = _result(
        _call(
            "trace",
            {
                "agent": "codex",
                "domain": "coding",
                "task": "Fix failing tests",
                "status": "partial",
                "event_type": "monitor.warning",
                "event_payload": {"message": "saw repeated command"},
            },
        )
    )
    assert "trace_id" in payload
    assert payload["event_recorded"] is True


def test_record_trace_persists_structured_workflow_progress(store_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = store_root
    monkeypatch.setattr(mcp_server, "_remote_client", None)
    mcp_server._current_ledger = None
    payload = _result(
        _call(
            "trace",
            {
                "agent": "copilot",
                "domain": "coding",
                "task": "Track plan progress",
                "status": "partial",
                "event_type": "plan_review",
                "event_payload": {
                    "workflow_step": "review",
                    "review_decision": "revise",
                    "plan_id": "02-01",
                },
            },
        )
    )
    assert "trace_id" in payload
    assert payload["event_recorded"] is True
    assert mcp_server._current_ledger is not None
    snapshot = mcp_server._current_ledger.snapshot()
    assert snapshot["plan_review"] == {
        "workflow_step": "review",
        "review_decision": "revise",
        "plan_id": "02-01",
    }


@pytest.mark.parametrize("review_decision", ["approve", "rerun"])
def test_record_trace_preserves_plan_review_receipt_for_other_decisions(
    store_root: Path, monkeypatch: pytest.MonkeyPatch, review_decision: str
) -> None:
    _ = store_root
    monkeypatch.setattr(mcp_server, "_remote_client", None)
    mcp_server._current_ledger = None
    payload = _result(
        _call(
            "trace",
            {
                "agent": "copilot",
                "domain": "coding",
                "task": "Track plan review",
                "status": "partial",
                "event_type": "plan_review",
                "event_payload": {
                    "workflow_step": "review",
                    "review_decision": review_decision,
                    "plan_id": "02-01",
                },
            },
        )
    )

    assert "trace_id" in payload
    assert payload["event_recorded"] is True
    assert mcp_server._current_ledger is not None
    assert mcp_server._current_ledger.snapshot()["plan_review"]["review_decision"] == review_decision


def test_record_trace_persists_task_progress_workflow_event(store_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = store_root
    monkeypatch.setattr(mcp_server, "_remote_client", None)
    mcp_server._current_ledger = None
    payload = _result(
        _call(
            "trace",
            {
                "agent": "copilot",
                "domain": "coding",
                "task": "Track task progress",
                "status": "partial",
                "event_type": "task_progress",
                "event_payload": {
                    "workflow_step": "execute",
                    "task_id": "02-02/task-1",
                    "completed_tasks": 2,
                    "remaining_tasks": 1,
                },
            },
        )
    )

    assert "trace_id" in payload
    assert payload["event_recorded"] is True
    assert mcp_server._current_ledger is not None
    assert mcp_server._current_ledger.snapshot()["task_progress"] == {
        "workflow_step": "execute",
        "task_id": "02-02/task-1",
        "completed_tasks": 2,
        "remaining_tasks": 1,
    }


def test_run_rubric_gate_pass(store_root: Path) -> None:
    _ = store_root
    payload = _result(
        _call(
            "verify",
            {
                "rubric_id": "rubric_state_change_safety",
                "checks": {
                    "canonical_identifier_used": True,
                    "pre_change_state_captured": True,
                    "read_after_write_completed": True,
                    "observed_state_matches_intent": True,
                    "rollback_plan_available": True,
                    "user_visible_surface_checked": True,
                },
            },
        )
    )
    assert payload["status"] == "pass"


def test_compact_session_call_returns_summary(store_root: Path) -> None:
    _ = store_root
    payload = _result(_call("compact", {}))
    assert "tokens_freed" in payload
    assert "prompt_block" in payload


def test_compact_auto_gate_requires_boundary_and_turns(store_root: Path) -> None:
    _ = store_root
    led = mcp_server._get_ledger()
    led.token_count = 160_000
    for idx in range(16):
        led.record("agent_message", f"working turn {idx}", {"idx": idx})

    waiting = mcp_server._compact_advise()
    assert waiting["should_advise"] is True
    assert waiting["should_compact"] is False
    assert waiting["task_boundary_detected"] is False

    led.record_test("pytest", passed=True, detail="tests passed")
    ready = mcp_server._compact_advise()
    assert ready["should_auto_compact"] is True
    assert ready["should_compact"] is True
    assert ready["task_boundary_detected"] is True


def test_compact_high_utilisation_bypasses_turns_gate(store_root: Path) -> None:
    # Five huge turns push utilisation to >=90% before the 15-turn gate is met.
    # The high-utilisation override should fire auto-compact at a task boundary
    # even though turn_count < AUTO_COMPACT_MIN_TURNS.
    _ = store_root
    led = mcp_server._get_ledger()
    led.token_count = 181_000  # 90.5% of 200k
    for idx in range(5):
        led.record("agent_message", f"dense turn {idx}", {"idx": idx})
    led.record_test("pytest", passed=True, detail="all green")

    result = mcp_server._compact_advise()
    assert result["turn_count"] < mcp_server.AUTO_COMPACT_MIN_TURNS
    assert result["should_auto_compact"] is True
    assert "override" in result["reason"] or "auto-compact threshold" in result["reason"]


def test_compact_handover_writes_markdown(store_root: Path) -> None:
    root = store_root
    led = mcp_server._get_ledger()
    led.session_id = "handover-session"
    led.task = "Finish a large refactor"
    led.token_count = 190_000
    led.record_file_event("src/app.py", "edit", diff="--- a/src/app.py\n+++ b/src/app.py\n")

    payload = mcp_server._compact_advise()

    assert payload["should_handover"] is True
    assert payload["handover_file"]
    handover_path = Path(payload["handover_file"])
    assert handover_path == root / "sessions" / "handover-session" / "HANDOVER.md"
    assert "Session Handover" in handover_path.read_text(encoding="utf-8")


def test_model_recommendation_emitted_before_tool_dispatch(store_root: Path) -> None:
    _ = store_root
    _result(_call("compact", {}))

    led = mcp_server._get_ledger()
    recommendations = [event for event in led.events if event.kind == "model_recommendation"]
    assert recommendations
    assert recommendations[-1].payload["tool_name"] == "compact"
    assert recommendations[-1].payload["tier"] in {"cheap", "medium", "expensive"}
    assert recommendations[-1].payload["lever"] == "model_routing"
    assert recommendations[-1].payload["tokens_saved"] == 0
    assert recommendations[-1].payload["cost_saved_usd"] >= 0


def test_model_recommendation_fallback_records_route_decision(
    monkeypatch: pytest.MonkeyPatch, store_root: Path
) -> None:
    from atelier.core.capabilities.cross_vendor_routing.configuration import RouteConfigError
    from atelier.infra.runtime.run_ledger import RunLedger

    def fail_recommend(*_: object, **__: object) -> dict[str, object]:
        raise RouteConfigError("disabled")

    monkeypatch.setattr(
        "atelier.core.capabilities.cross_vendor_routing.router.CrossVendorRouter.recommend",
        fail_recommend,
    )
    ledger = RunLedger(session_id="route-fallback", root=store_root)

    payload = mcp_server._emit_model_recommendation("read", {}, ledger)
    route_decisions = [event for event in ledger.events if event.kind == "route_decision"]

    assert payload["kind"] == "model_recommendation"
    assert route_decisions
    assert route_decisions[-1].payload["kind"] == "route_decision"


def test_compact_session_op_emits_session_compaction_savings(monkeypatch: pytest.MonkeyPatch, store_root: Path) -> None:
    _ = store_root
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(mcp_server, "_append_live_savings_event", lambda event: events.append(event))
    led = mcp_server._get_ledger()
    led.token_count = 48_000
    for idx in range(4):
        led.record("agent_message", f"working turn {idx}", {"idx": idx})

    payload = mcp_server._compress_context()

    session_events = [event for event in events if event.get("kind") == "session_compaction"]
    assert session_events
    assert session_events[-1]["lever"] == "session_compaction"
    assert session_events[-1]["tokens_saved"] > 0
    assert session_events[-1]["cost_saved_usd"] >= 0
    assert payload["tokens_freed"] == session_events[-1]["tokens_saved"]
    assert payload["cost_saved_usd"] == session_events[-1]["cost_saved_usd"]


def test_compact_advise_emits_session_compaction_savings_when_auto_compacting(
    monkeypatch: pytest.MonkeyPatch, store_root: Path
) -> None:
    _ = store_root
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(mcp_server, "_append_live_savings_event", lambda event: events.append(event))
    led = mcp_server._get_ledger()
    led.token_count = 160_000
    for idx in range(16):
        led.record("agent_message", f"working turn {idx}", {"idx": idx})
    led.record_test("pytest", passed=True, detail="tests passed")

    payload = mcp_server._compact_advise()

    session_events = [event for event in events if event.get("kind") == "session_compaction"]
    assert payload["should_compact"] is True
    assert session_events
    assert session_events[-1]["trigger"] == "compact_advise"
    assert session_events[-1]["tokens_saved"] == payload["tokens_freed"]
    assert session_events[-1]["cost_saved_usd"] == payload["cost_saved_usd"]


def test_detect_agent_supports_all_five_cli_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    for host in ("claude", "codex", "copilot", "opencode", "antigravity"):
        monkeypatch.setenv("ATELIER_AGENT", host)
        assert mcp_server._detect_agent() == host
        monkeypatch.delenv("ATELIER_AGENT", raising=False)


def test_smart_read_and_search_surfaces(store_root: Path, tmp_path: Path) -> None:
    _ = store_root
    target = tmp_path / "sample.py"
    target.write_text("def alpha():\n    return 'needle'\n", encoding="utf-8")

    read_payload = _result(_call("read", {"path": str(target)}))
    assert "def alpha()" in read_payload
    assert "needle" in read_payload

    search_payload = _result(_call("search", {"query": "needle", "path": str(tmp_path)}))
    assert "### " in search_payload

    grep_payload = _result(_call("grep", {"path": str(target), "content_regex": "needle"}))
    assert grep_payload
    assert "_meta" not in grep_payload

    legacy_payload = _result(_call("grep", {"path": str(target), "content_regex": "needle", "include_meta": True}))
    assert "sample.py" in legacy_payload


def test_smart_read_batch_accepts_string_paths(store_root: Path, tmp_path: Path) -> None:
    """Batch read must accept plain string paths, dict specs, and a mix of both.

    Regression: `files` previously required `list[dict]`, so the natural
    `read(files=["a.py", "b.py"])` call failed Pydantic validation with a
    list/dict type error before reaching the handler.
    """
    _ = store_root
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("alpha_val = 1\n", encoding="utf-8")
    b.write_text("beta_val = 2\n", encoding="utf-8")

    # Plain strings. Reaching a non-error result at all proves the list[str]
    # input passed Pydantic validation; both files must be present.
    payload = _result(_call("read", {"files": [str(a), str(b)]}))
    assert "alpha_val" in payload
    assert "beta_val" in payload

    # Mixed strings and dict specs in one batch.
    mixed = _result(_call("read", {"files": [str(a), {"path": str(b), "range": "1-1"}]}))
    assert "alpha_val" in mixed
    assert "beta_val" in mixed


def test_smart_read_batch_honors_top_level_expand(store_root: Path, tmp_path: Path) -> None:
    """A top-level ``expand=True`` must apply to every batched file.

    Regression: the batch loop read ``expand`` only from each per-file spec
    (``spec.get("expand", False)``), silently dropping a top-level
    ``expand=True``. Plain-string entries therefore fell back to the >200-LOC
    outline projection (bodies omitted) even though the caller asked for full
    bodies. All prior ``expand`` coverage used single-path reads, which take a
    different code path, so the batch gap went untested.
    """
    _ = store_root
    big = tmp_path / "big_module.py"
    # >200 LOC so the default projection is outline (bodies omitted). The marker
    # lives inside a function body, which outline drops and expand keeps.
    body = ["def head():", "    return 0", ""]
    body += [f"const_{i} = {i}" for i in range(250)]
    body += ["", "def carries_marker():", "    leaf = 'UNIQUE_BODY_TOKEN'", "    return leaf", ""]
    big.write_text("\n".join(body), encoding="utf-8")

    # Without expand: outline projection, the in-body marker is omitted.
    outline = _result(_call("read", {"files": [str(big)]}))
    assert "UNIQUE_BODY_TOKEN" not in outline

    # Top-level expand=True must reach every plain-string batch entry.
    expanded = _result(_call("read", {"files": [str(big)], "expand": True}))
    assert "UNIQUE_BODY_TOKEN" in expanded

    # A per-file expand still works and overrides the top-level default.
    per_file = _result(_call("read", {"files": [{"path": str(big), "expand": True}]}))
    assert "UNIQUE_BODY_TOKEN" in per_file


def test_smart_read_batch_honors_top_level_max_lines(store_root: Path, tmp_path: Path) -> None:
    """A top-level ``max_lines`` must apply to every batched file.

    Same bug class as the ``expand`` drop: the batch loop read ``max_lines``
    only from each per-file spec (``spec.get("max_lines")``), discarding a
    top-level ``max_lines``. A caller capping every file in a batch silently
    got the default projection instead of the head-summary cap.
    """
    _ = store_root
    big = tmp_path / "big_module.py"
    big.write_text("\n".join(f"line_{i} = {i}" for i in range(300)), encoding="utf-8")

    # Top-level max_lines must reach each batched file -> summary (head-cap) mode.
    capped = mcp_server.tool_smart_read({"files": [str(big)], "max_lines": 3})
    assert capped["files"][0].get("mode") == "summary"

    # Without it, the same large file is not summary-capped (proves the cap came
    # from the top-level arg, not the file size).
    plain = mcp_server.tool_smart_read({"files": [str(big)]})
    assert plain["files"][0].get("mode") != "summary"


def test_node_accepts_path_line_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    """`node` parses a "path#line" suffix into the positional line, like read/edit."""
    captured: dict[str, Any] = {}

    def fake_op_node(**kwargs: Any) -> dict[str, Any]:
        captured.clear()
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(mcp_server, "_op_node", fake_op_node)

    mcp_server.tool_node({"path": "store.py#100"})
    assert captured["path"] == "store.py"
    assert captured["line"] == 100

    # An explicit line wins; the suffix is still stripped off the path.
    mcp_server.tool_node({"path": "store.py#100", "line": 42})
    assert captured["path"] == "store.py"
    assert captured["line"] == 42


def test_scope_search_matches_to_range_filters_snippets() -> None:
    payload: dict[str, Any] = {
        "matches": [
            {"path": "a.py", "snippets": [{"line_start": 1, "line_end": 5}, {"line_start": 80, "line_end": 90}]},
            {"path": "b.py", "snippets": [{"line_start": 200, "line_end": 210}]},
            {"path": "c.py"},  # no snippet line data -> cannot filter, kept
        ],
        "match_paths": ["a.py", "b.py", "c.py"],
    }
    mcp_server._scope_search_matches_to_range(payload, (1, 50))
    assert [m["path"] for m in payload["matches"]] == ["a.py", "c.py"]
    a = next(m for m in payload["matches"] if m["path"] == "a.py")
    assert a["snippets"] == [{"line_start": 1, "line_end": 5}]
    assert payload["match_paths"] == ["a.py", "c.py"]


def test_smart_edit_surface_applies_patch(store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = store_root
    monkeypatch.chdir(tmp_path)
    target = Path("edit.txt")
    target.write_text("hello world", encoding="utf-8")

    payload = _result(
        _call(
            "edit",
            {
                "edits": [
                    {
                        "path": str(target),
                        "op": "replace",
                        "old_string": "world",
                        "new_string": "atelier",
                    }
                ]
            },
        )
    )
    assert payload["applied"] == ["edit.txt:1"]
    assert target.read_text(encoding="utf-8") == "hello atelier"


def test_smart_edit_compacts_hunks_by_path(store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = store_root
    monkeypatch.chdir(tmp_path)
    first = Path("first.txt")
    second = Path("second.txt")
    first.write_text("one\ntwo\nthree\n", encoding="utf-8")
    second.write_text("alpha\nbeta\n", encoding="utf-8")

    payload = _result(
        _call(
            "edit",
            {
                "edits": [
                    {"path": str(first), "op": "replace", "old_string": "one", "new_string": "ONE"},
                    {"path": str(first), "op": "replace", "old_string": "three", "new_string": "THREE"},
                    {"path": str(second), "op": "replace", "old_string": "alpha\nbeta", "new_string": "ALPHA\nBETA"},
                ],
                "post_edit_hooks": False,
            },
        )
    )

    assert payload["applied"] == ["first.txt:1,3", "second.txt:1-2"]
    # 3 hunks but only 2 distinct files: built-in MultiEdit already batches the
    # two same-file hunks, so the honest cross-file saving is distinct_files - 1.
    assert payload["calls_saved"] == 1


def test_smart_edit_same_file_hunks_credit_no_calls(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiple hunks in ONE file are not a saving — MultiEdit already batches them."""
    _ = store_root
    monkeypatch.chdir(tmp_path)
    target = Path("only.txt")
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")

    payload = _result(
        _call(
            "edit",
            {
                "edits": [
                    {"path": str(target), "op": "replace", "old_string": "one", "new_string": "ONE"},
                    {"path": str(target), "op": "replace", "old_string": "two", "new_string": "TWO"},
                    {"path": str(target), "op": "replace", "old_string": "three", "new_string": "THREE"},
                ],
                "post_edit_hooks": False,
            },
        )
    )

    assert payload["applied"] == ["only.txt:1,2,3"]
    # One distinct file => no honest cross-file saving.
    assert payload.get("calls_saved", 0) == 0


def test_smart_edit_cross_file_credit_matches_distinct_files(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One hunk each across N files => calls_saved == N - 1."""
    _ = store_root
    monkeypatch.chdir(tmp_path)
    files = [Path(f"f{i}.txt") for i in range(3)]
    for f in files:
        f.write_text("target\n", encoding="utf-8")

    payload = _result(
        _call(
            "edit",
            {
                "edits": [
                    {"path": str(f), "op": "replace", "old_string": "target", "new_string": "DONE"} for f in files
                ],
                "post_edit_hooks": False,
            },
        )
    )

    assert payload["calls_saved"] == len(files) - 1


def test_smart_edit_flags_existing_test_contract_changes(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = store_root
    monkeypatch.chdir(tmp_path)
    target = Path("tests/test_parser.rs")
    target.parent.mkdir()
    target.write_text('assert_eq!(message, "old");\n', encoding="utf-8")

    payload = _result(
        _call(
            "edit",
            {
                "edits": [
                    {
                        "file_path": str(target),
                        "old_string": 'assert_eq!(message, "old");',
                        "new_string": 'assert_eq!(message, "new");',
                    }
                ],
                "post_edit_hooks": False,
            },
        )
    )

    assert payload["rolled_back"] is True
    assert payload["writes"] == 0
    assert payload["contract_review"]["required"] is True
    assert payload["contract_review"]["paths"] == ["tests/test_parser.rs"]
    assert 'assert_eq!(message, "old");' in target.read_text(encoding="utf-8")


def test_smart_edit_allows_reviewed_existing_test_contract_change(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = store_root
    monkeypatch.chdir(tmp_path)
    target = Path("tests/test_parser.rs")
    target.parent.mkdir()
    target.write_text('assert_eq!(message, "old");\n', encoding="utf-8")
    evidence = "The user explicitly requested changing the parser error contract."

    payload = _result(
        _call(
            "edit",
            {
                "edits": [
                    {
                        "file_path": str(target),
                        "old_string": 'assert_eq!(message, "old");',
                        "new_string": 'assert_eq!(message, "new");',
                    }
                ],
                "post_edit_hooks": False,
                "allow_test_contract_change": True,
                "contract_change_evidence": evidence,
            },
        )
    )

    assert payload["rolled_back"] is False
    assert payload["applied"] == ["tests/test_parser.rs:1"]
    assert payload["contract_review"]["evidence"] == evidence
    assert 'assert_eq!(message, "new");' in target.read_text(encoding="utf-8")


def test_smart_edit_does_not_flag_new_regression_test(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = store_root
    monkeypatch.chdir(tmp_path)
    target = Path("tests/regression/issue.rs")

    payload = _result(
        _call(
            "edit",
            {
                "edits": [
                    {
                        "file_path": str(target),
                        "new_string": "#[test]\nfn regression() {}\n",
                        "overwrite": True,
                    }
                ],
                "post_edit_hooks": False,
            },
        )
    )

    assert "contract_review" not in payload


def test_smart_edit_rejects_mixed_descriptor_families(store_root: Path, tmp_path: Path) -> None:
    _ = store_root
    target = tmp_path / "mixed.txt"
    target.write_text("hello world", encoding="utf-8")

    resp = _call(
        "edit",
        {
            "edits": [
                {
                    "path": str(target),
                    "op": "replace",
                    "old_string": "world",
                    "new_string": "legacy",
                },
                {"file_path": str(target), "old_string": "hello", "new_string": "rich"},
            ]
        },
    )

    assert "error" in resp
    assert "cannot mix legacy" in resp["error"]["message"]
    assert target.read_text(encoding="utf-8") == "hello world"


def test_smart_edit_legacy_rejects_protected_paths(store_root: Path, tmp_path: Path) -> None:
    _ = store_root
    protected = tmp_path / ".atelier" / "state.txt"
    protected.write_text("hello world", encoding="utf-8")

    payload = _result(
        _call(
            "edit",
            {
                "edits": [
                    {
                        "path": str(protected),
                        "op": "replace",
                        "old_string": "world",
                        "new_string": "atelier",
                    }
                ]
            },
        )
    )

    assert payload["rolled_back"] is True
    assert "Protected path denied" in payload["failed"][0]["error"]
    assert protected.read_text(encoding="utf-8") == "hello world"


def test_smart_edit_records_workspace_relative_diff_after_hooks(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = store_root
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other_cwd = tmp_path / "cwd"
    other_cwd.mkdir()
    target = workspace / "edit.txt"
    target.write_text("hello world", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.chdir(other_cwd)

    def fake_hooks(files: list[str], *, repo_root: Path, config: object) -> object:
        target.write_text("hello hooks", encoding="utf-8")

        class HookResult:
            diagnostics: tuple[object, ...] = ()
            steps_ran: tuple[str, ...] = ("fake-format",)
            steps_skipped: tuple[str, ...] = ()
            steps_failed: tuple[str, ...] = ()
            total_ms: int = 1

        return HookResult()

    monkeypatch.setattr(
        "atelier.core.capabilities.tool_supervision.post_edit_hooks.run_post_edit_hooks",
        fake_hooks,
    )

    payload = _result(
        _call(
            "edit",
            {
                "post_edit_hooks": True,
                "edits": [
                    {
                        "file_path": "edit.txt",
                        "old_string": "world",
                        "new_string": "atelier",
                    }
                ],
            },
        )
    )

    assert payload["failed"] == []
    assert target.read_text(encoding="utf-8") == "hello hooks"
    file_events = [event for event in mcp_server._get_ledger().events if event.kind == "file_edit"]
    assert file_events[-1].payload["path"] == "edit.txt"
    assert "hello hooks" in file_events[-1].payload["diff"]
    assert "hello atelier" not in file_events[-1].payload["diff"]


def test_code_context_external_scope_surface_returns_external_hits_only(store_root: Path, tmp_path: Path) -> None:
    _ = store_root
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    _write_gateway_scip_fixture(
        tmp_path,
        symbol_id="scip-requests-get",
        artifact_name="external-python.scip",
        file_path="external/requests/api.py",
        symbol_name="get",
        qualified_name="requests.get",
        source="def get(url: str) -> str:\n    return url\n",
    )

    repo_payload = mcp_server._op_search(repo_root=str(tmp_path), query="get")
    external_payload = mcp_server._op_search(repo_root=str(tmp_path), query="get", scope="external")

    assert repo_payload["items"] == []
    assert [item["qualified_name"] for item in external_payload["items"]] == ["requests.get"]
    assert external_payload["items"][0]["origin"] == "external"


def test_edit_symbol_rejects_external_target_cleanly(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = store_root
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    _write_gateway_scip_fixture(
        tmp_path,
        symbol_id="scip-requests-get",
        artifact_name="external-python.scip",
        file_path="external/requests/api.py",
        symbol_name="get",
        qualified_name="requests.get",
        source="def get(url: str) -> str:\n    return url\n",
    )

    payload = tool_smart_edit(
        {
            "edits": [
                {
                    "kind": "symbol",
                    "symbol_id": "scip-requests-get",
                    "mode": "replace",
                    "new_body": "def get(url: str) -> str:\n    return 'patched'\n",
                }
            ]
        }
    )

    assert payload["rolled_back"] is True
    assert payload["failed"][0]["error"] == "external_symbol_edit_not_allowed"


def test_code_context_workspace_search_returns_repo_tagged_hits_and_repo_filter(
    store_root: Path,
    tmp_path: Path,
) -> None:
    _ = store_root
    billing_root = tmp_path.parent / "billing"
    _write_workspace_fixture_repo(tmp_path, module_name="atelier")
    _write_workspace_fixture_repo(billing_root, module_name="billing")
    _write_workspace_fixture_config(tmp_path, billing_root)

    payload = mcp_server._op_search(repo_root=str(tmp_path), query="SharedConfig", budget_tokens=4000)
    billing_only = mcp_server._op_search(
        repo_root=str(tmp_path),
        query="SharedConfig",
        repo="billing",
        budget_tokens=4000,
    )

    assert [(item["repo_name"], item["path"]) for item in payload["items"]] == [
        ("atelier", "src/config.py"),
        ("billing", "src/config.py"),
    ]
    assert [item["repo_name"] for item in billing_only["items"]] == ["billing"]


def test_code_context_workspace_symbol_filter_and_external_origin_metadata(
    store_root: Path,
    tmp_path: Path,
) -> None:
    _ = store_root
    billing_root = tmp_path.parent / "billing"
    _write_workspace_fixture_repo(tmp_path, module_name="atelier")
    _write_workspace_fixture_repo(billing_root, module_name="billing")
    _write_workspace_fixture_config(tmp_path, billing_root)
    _write_gateway_scip_fixture(
        billing_root,
        symbol_id="scip-requests-get",
        artifact_name="external-python.scip",
        file_path="external/requests/api.py",
        symbol_name="get",
        qualified_name="requests.get",
        source="def get(url: str) -> str:\n    return url\n",
    )

    default_symbol = mcp_server._op_node(repo_root=str(tmp_path), symbol_name="SharedConfig")
    billing_symbol = mcp_server._op_node(
        repo_root=str(tmp_path),
        symbol_name="SharedConfig",
        repo="billing",
    )
    external_payload = mcp_server._op_search(
        repo_root=str(tmp_path),
        query="get",
        scope="external",
        repo="billing",
    )

    assert default_symbol["repo_name"] == "atelier"
    assert billing_symbol["repo_name"] == "billing"
    assert billing_symbol["qualified_name"] == "SharedConfig"
    assert external_payload["items"][0]["repo_name"] == "billing"
    assert external_payload["items"][0]["origin"] == "external"


def test_repo_map_surface(store_root: Path, tmp_path: Path) -> None:
    _ = store_root
    target = tmp_path / "sample.py"
    target.write_text("def alpha():\n    return 1\n", encoding="utf-8")

    payload = _result(
        _call(
            "search",
            {"query": "", "seed_files": [str(target)], "mode": "map", "budget_tokens": 200},
        )
    )
    # map mode now renders compact markdown (repo_map heading + file list)
    # instead of the raw JSON payload.
    assert isinstance(payload, str)
    assert "### repo_map" in payload
    assert "sample.py" in payload


def test_code_context_mcp_surfaces(store_root: Path, tmp_path: Path) -> None:
    _ = store_root
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from a import alpha\n\ndef beta():\n    return alpha()\n", encoding="utf-8")

    indexed = _result(_call("index", {"repo_root": str(tmp_path)}))
    _m = re.search(r"symbols=(\d+)", indexed)
    assert _m is not None
    assert int(_m.group(1)) >= 2
    assert "provenance: local" in indexed

    searched = _result(_call("symbols", {"repo_root": str(tmp_path), "query": "alpha"}))
    assert searched and "no matches" not in searched
    assert "snippet:" not in searched
    cached_search = _result(_call("symbols", {"repo_root": str(tmp_path), "query": "alpha"}))
    assert "provenance: cached" in cached_search

    symbol = _op_result(
        "node",
        mcp_server._op_node,
        repo_root=str(tmp_path),
        qualified_name="alpha",
        path="a.py",
    )
    assert "def alpha" in symbol

    context = _result(
        _call(
            "context",
            {
                "task": "change alpha",
                "files": ["a.py"],
                "token_budget": 4000,
                "mode": "symbols",
            },
        )
    )
    assert isinstance(context, dict)
    assert context.get("task") == "change alpha"


def test_code_context_mcp_routes_scip_and_invalidates_cache(store_root: Path, tmp_path: Path) -> None:
    _ = store_root
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    artifact_path = _write_gateway_scip_fixture(tmp_path, symbol_id="scip-alpha-v1")

    first = _result(_call("symbols", {"repo_root": str(tmp_path), "query": "alpha"}))
    cached = _result(_call("symbols", {"repo_root": str(tmp_path), "query": "alpha"}))
    artifact_path.write_text(
        artifact_path.read_text(encoding="utf-8").replace("scip-alpha-v1", "scip-alpha-v2"),
        encoding="utf-8",
    )
    fresh = _result(_call("symbols", {"repo_root": str(tmp_path), "query": "alpha"}))

    assert first["provenance"] == "scip" if isinstance(first, dict) else "provenance: scip" in first
    assert cached["provenance"] == "cached" if isinstance(cached, dict) else "provenance: cached" in cached
    assert fresh["provenance"] == "scip" if isinstance(fresh, dict) else "provenance: scip" in fresh


def test_code_context_search_surface_supports_snippet_scope_and_glob(store_root: Path, tmp_path: Path) -> None:
    _ = store_root
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "orders.py").write_text(
        "class OrderService:\n    def calculate_total(self, items: list[int]) -> int:\n        return sum(items)\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_orders.py").write_text(
        "from src.orders import OrderService\n",
        encoding="utf-8",
    )

    payload = mcp_server._op_search(
        repo_root=str(tmp_path),
        query="OrderService",
        snippet="head",
        snippet_lines=2,
        file_glob="src/*.py",
        scope="repo",
        budget_tokens=4000,
    )

    assert "provenance" not in payload
    assert "provenance_breakdown" not in payload
    assert payload["items"][0]["path"] == "src/orders.py"
    assert (
        payload["items"][0]["snippet"] == "class OrderService:\n    def calculate_total(self, items: list[int]) -> int:"
    )


def test_tool_code_search_dispatches_mode_without_gateway_ranking_logic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_engine = MagicMock()
    fake_engine.tool_search.return_value = {
        "items": [{"symbol_name": "issue_access_token", "provenance": "local"}],
        "cache_hit": False,
        "provenance": "local",
        "tokens_saved": 10,
        "total_tokens": 80,
        "mode": "semantic",
    }
    monkeypatch.setattr(
        "atelier.gateway.adapters.mcp_server._code_context_engine",
        lambda repo_root=".": fake_engine,
    )

    payload = mcp_server._op_search(
        repo_root=str(tmp_path),
        query="create login token for authenticated user",
        mode="semantic",
        budget_tokens=220,
    )

    assert "mode" not in payload
    fake_engine.tool_search.assert_called_once_with(
        "create login token for authenticated user",
        limit=20,
        mode="semantic",
        intent="auto",
        kind=None,
        language=None,
        seed_files=None,
        snippet="none",
        snippet_lines=8,
        file_glob=None,
        scope="repo",
        budget_tokens=220,
    )


def test_tool_code_search_dispatches_grounded_seed_files_without_gateway_ranking_logic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_engine = MagicMock()
    fake_engine.tool_search.return_value = {
        "items": [{"symbol_name": "OrderService", "provenance": "local"}],
        "cache_hit": False,
        "provenance": "local",
        "tokens_saved": 6,
        "total_tokens": 60,
        "mode": "lexical",
    }
    monkeypatch.setattr(
        "atelier.gateway.adapters.mcp_server._code_context_engine",
        lambda repo_root=".": fake_engine,
    )

    payload = mcp_server._op_search(
        repo_root=str(tmp_path),
        query="OrderService",
        seed_files=["src/orders.py"],
        budget_tokens=220,
    )

    assert "mode" not in payload
    fake_engine.tool_search.assert_called_once_with(
        "OrderService",
        limit=20,
        mode="auto",
        intent="auto",
        kind=None,
        language=None,
        seed_files=["src/orders.py"],
        snippet="none",
        snippet_lines=8,
        file_glob=None,
        scope="repo",
        budget_tokens=220,
    )


def test_tool_code_search_dispatches_deleted_scope_filters_without_gateway_history_logic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_engine = MagicMock()
    fake_engine.tool_search.return_value = {
        "items": [
            {
                "symbol_name": "LegacyCheckout",
                "provenance": "graveyard",
                "deleted_at_sha": "abc123",
                "rename_target": "modern.py",
            }
        ],
        "cache_hit": False,
        "provenance": "graveyard",
        "tokens_saved": 11,
        "total_tokens": 120,
        "mode": "auto",
    }
    monkeypatch.setattr(
        "atelier.gateway.adapters.mcp_server._code_context_engine",
        lambda repo_root=".": fake_engine,
    )

    payload = mcp_server._op_search(
        repo_root=str(tmp_path),
        query="ModernCheckout",
        scope="deleted",
        since="2025-01-01",
        touched_by="history@example.com",
        budget_tokens=220,
    )

    assert "provenance" not in payload
    assert payload["items"][0]["rename_target"] == "modern.py"
    fake_engine.tool_search.assert_called_once_with(
        "ModernCheckout",
        limit=20,
        mode="auto",
        kind=None,
        language=None,
        snippet="none",
        snippet_lines=8,
        file_glob=None,
        scope="deleted",
        since="2025-01-01",
        touched_by="history@example.com",
        budget_tokens=220,
    )


def test_tool_code_blame_dispatches_additively_without_gateway_aggregation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_engine = MagicMock()
    fake_engine.tool_blame.return_value = {
        "symbol_name": "risk_score",
        "qualified_name": "risk_score",
        "file_path": "service.py",
        "freshness": "fresh",
        "last_author": "carol@example.com",
        "last_commit_sha": "abc123",
        "local_edits": False,
        "distinct_authors": 2,
        "cache_hit": False,
        "provenance": "blame",
        "tokens_saved": 12,
        "total_tokens": 150,
    }
    monkeypatch.setattr(
        "atelier.gateway.adapters.mcp_server._code_context_engine",
        lambda repo_root=".": fake_engine,
    )

    payload = mcp_server._op_blame(
        repo_root=str(tmp_path),
        query="risk_score",
        include_churn=False,
        budget_tokens=220,
    )

    assert "provenance" not in payload
    assert payload["symbol_name"] == "risk_score"
    fake_engine.tool_blame.assert_called_once_with(
        query="risk_score",
        symbol_id=None,
        qualified_name=None,
        symbol_name=None,
        file_path=None,
        include_churn=False,
        budget_tokens=220,
    )


def test_tool_code_include_churn_remains_additive_for_non_blame_ops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_engine = MagicMock()
    fake_engine.tool_search.return_value = {
        "items": [{"symbol_name": "OrderService", "file_path": "src/orders.py", "provenance": "local"}],
        "cache_hit": False,
        "provenance": "local",
        "tokens_saved": 10,
        "total_tokens": 100,
        "mode": "auto",
    }
    monkeypatch.setattr(
        "atelier.gateway.adapters.mcp_server._code_context_engine",
        lambda repo_root=".": fake_engine,
    )

    payload = mcp_server._op_search(
        repo_root=str(tmp_path),
        query="OrderService",
        budget_tokens=220,
    )

    assert "provenance" not in payload
    fake_engine.tool_search.assert_called_once_with(
        "OrderService",
        limit=20,
        mode="auto",
        kind=None,
        language=None,
        snippet="none",
        snippet_lines=8,
        file_glob=None,
        scope="repo",
        budget_tokens=220,
        intent="auto",
        seed_files=None,
    )


def test_code_context_usages_surface_groups_references(store_root: Path, tmp_path: Path) -> None:
    _ = store_root
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "orders.py").write_text(
        "class OrderService:\n    def calculate_total(self, items: list[int]) -> int:\n        return sum(items)\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "checkout.py").write_text(
        "from src.orders import OrderService\n\n"
        "def checkout(items: list[int]) -> int:\n"
        "    return OrderService().calculate_total(items)\n",
        encoding="utf-8",
    )

    payload = _op_result(
        "usages",
        mcp_server._op_usages,
        repo_root=str(tmp_path),
        query="OrderService",
    )

    assert "### usages" in payload
    assert "OrderService" in payload
    assert "src/checkout.py" in payload
    assert "local_index" in payload


def test_code_context_mcp_falls_back_when_scip_artifact_is_invalid(store_root: Path, tmp_path: Path) -> None:
    _ = store_root
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    engine = CodeContextEngine(tmp_path)
    artifact_dir = ScipIndexer(tmp_path, engine.repo_id).cache_root
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "python.scip").write_text("{invalid json", encoding="utf-8")

    searched = _result(_call("symbols", {"repo_root": str(tmp_path), "query": "alpha"}))

    assert "alpha" in searched
    assert "provenance: scip" not in searched


def test_code_context_pattern_search_surface_is_cached(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = store_root
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("requests.get(url)\n", encoding="utf-8")

    monkeypatch.setattr(
        "atelier.core.capabilities.code_context.engine.AstGrepAdapter.search",
        lambda self, *, pattern, language=None, file_glob=None, limit=20: PatternSearchResult(
            matches=[
                PatternMatch(
                    file_path="src/app.py",
                    line=1,
                    column=0,
                    end_line=1,
                    end_column=17,
                    snippet="requests.get(url)",
                    captures={"URL": "url"},
                )
            ],
            truncated=False,
            total_matches=1,
        ),
    )

    first = _op_result(
        "codemod",
        mcp_server._op_pattern,
        repo_root=str(tmp_path),
        pattern="requests.get($URL)",
        budget_tokens=220,
    )
    cached = _op_result(
        "codemod",
        mcp_server._op_pattern,
        repo_root=str(tmp_path),
        pattern="requests.get($URL)",
        budget_tokens=220,
    )

    # Pattern search now surfaces the compact markdown the agent receives, not
    # the raw JSON payload (path emitted once, snippet preserved).
    assert isinstance(first, str)
    assert first.startswith("### pattern")
    assert "src/app.py" in first
    assert "requests.get(url)" in first
    assert "provenance" not in first
    # Cache state is internal bookkeeping; the cached response must be identical.
    assert cached == first


def test_code_context_cache_diagnostics_surface_is_additive(store_root: Path, tmp_path: Path) -> None:
    _ = store_root
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "orders.py").write_text(
        "class OrderService:\n    def calculate_total(self, items: list[int]) -> int:\n        return sum(items)\n",
        encoding="utf-8",
    )

    _op_result(
        "search",
        mcp_server._op_search,
        repo_root=str(tmp_path),
        query="OrderService",
        budget_tokens=4000,
    )
    _op_result(
        "node",
        mcp_server._op_node,
        repo_root=str(tmp_path),
        qualified_name="OrderService",
        path="src/orders.py",
        budget_tokens=4000,
    )

    status = _result(_call("cache_status", {"repo_root": str(tmp_path), "budget_tokens": 200}))
    invalidated = _result(
        _call(
            "cache_invalidate",
            {
                "repo_root": str(tmp_path),
                "cache_tool": "search",
                "budget_tokens": 200,
            },
        )
    )

    assert "code.search=1" in status and "code.symbol=1" in status
    assert "items" not in status
    assert "matches" not in status
    assert invalidated["scope"]["cache_tool"] == "search"
    assert invalidated["invalidated_entries"] == 1


def test_code_context_pattern_rewrite_reindexes_changed_files(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = store_root
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("requests.get(url)\n", encoding="utf-8")

    def fake_rewrite(self, *, pattern, rewrite, language=None, file_glob=None, dry_run=True):  # type: ignore[no-untyped-def]
        before = target.read_text(encoding="utf-8")
        after = before.replace("requests.get(url)", "requests.get(url, timeout=30)")
        diff = "--- a/src/app.py\n+++ b/src/app.py\n@@\n-requests.get(url)\n+requests.get(url, timeout=30)\n"
        if not dry_run:
            target.write_text(after, encoding="utf-8")
        return PatternRewriteResult(diff=diff, files_changed=["src/app.py"])

    reindexed: list[list[str]] = []

    monkeypatch.setattr("atelier.core.capabilities.code_context.engine.AstGrepAdapter.rewrite", fake_rewrite)
    monkeypatch.setattr(
        CodeContextEngine,
        "_reindex_files",
        lambda self, file_paths: reindexed.append(list(file_paths)),
        raising=False,
    )

    preview = _op_result(
        "codemod",
        mcp_server._op_pattern,
        repo_root=str(tmp_path),
        pattern="requests.get($URL)",
        rewrite="requests.get($URL, timeout=30)",
        dry_run=True,
    )
    applied = _op_result(
        "codemod",
        mcp_server._op_pattern,
        repo_root=str(tmp_path),
        pattern="requests.get($URL)",
        rewrite="requests.get($URL, timeout=30)",
        dry_run=False,
    )

    assert "--- a/src/app.py" in preview["diff"]
    assert applied["files_changed"] == ["src/app.py"]
    assert reindexed == [["src/app.py"]]
    assert target.read_text(encoding="utf-8") == "requests.get(url, timeout=30)\n"


def test_code_context_pattern_returns_structured_tool_unavailable(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = store_root
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("requests.get(url)\n", encoding="utf-8")

    payload = {
        "error": "tool_unavailable",
        "tool": "ast-grep",
        "expected_binary": "ast-grep",
        "message": "ast-grep is unavailable",
        "checked": [],
        "hint": "install ast-grep",
    }
    monkeypatch.setattr(
        "atelier.core.capabilities.code_context.engine.AstGrepAdapter.search",
        lambda self, *, pattern, language=None, file_glob=None, limit=20: (_ for _ in ()).throw(
            AstGrepToolUnavailable(payload)
        ),
    )

    result = mcp_server._op_pattern(
        repo_root=str(tmp_path),
        pattern="requests.get($URL)",
    )

    assert result["error"] == "tool_unavailable"
    assert result["expected_binary"] == "ast-grep"


# ---------------------------------------------------------------------------
# Remaining-gap regression tests (Issues 4, 13, 14 and shell failure fix)
# ---------------------------------------------------------------------------


def test_path_safety_module_is_importable_and_has_protected_parts() -> None:
    """Centralised PROTECTED_PARTS frozenset must exist and cover the canonical dirs."""
    from atelier.core.capabilities.tool_supervision.path_safety import PROTECTED_PARTS

    required = {".git", ".atelier", "node_modules", ".venv"}
    assert required <= set(PROTECTED_PARTS), f"Missing entries: {required - set(PROTECTED_PARTS)}"


def test_batch_edit_and_rich_edit_share_path_safety_constant() -> None:
    """Both edit modules must reference the same PROTECTED_PARTS set (no local forks)."""
    from atelier.core.capabilities.tool_supervision import batch_edit, rich_edit
    from atelier.core.capabilities.tool_supervision.path_safety import PROTECTED_PARTS

    # Neither module should define its own _PROTECTED_PARTS
    assert not hasattr(batch_edit, "_PROTECTED_PARTS"), "batch_edit still has local _PROTECTED_PARTS"
    assert not hasattr(rich_edit, "_PROTECTED_PARTS"), "rich_edit still has local _PROTECTED_PARTS"

    # Both modules reference the shared path_safety.PROTECTED_PARTS constant
    assert batch_edit._resolve_path.__globals__["PROTECTED_PARTS"] is PROTECTED_PARTS
    assert rich_edit._resolve.__globals__["PROTECTED_PARTS"] is PROTECTED_PARTS


def test_trace_compact_receipt_always_present(store_root: Path) -> None:
    """tool_record_trace must always return trace_id and event_recorded — the compact receipt."""
    _ = store_root
    payload = _result(
        _call(
            "trace",
            {
                "agent": "atelier:code",
                "domain": "mcp-server",
                "task": "Verify compact receipt",
                "status": "success",
            },
        )
    )
    assert payload.get("event_recorded") is True, f"'event_recorded' missing or False in trace receipt: {payload}"
    assert isinstance(payload.get("trace_id"), str) and payload["trace_id"], (
        f"'trace_id' missing or empty in trace receipt: {payload}"
    )


def test_shell_failure_preserves_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """For failing commands, the tail of stdout must be preserved even when output is long."""
    from atelier.gateway.adapters.mcp_server import _run_shell_tool

    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))

    # Generate 300 numbered lines then exit 1 — only tail should survive truncation
    result = _run_shell_tool(
        "python3 -c \"import sys; [print(f'line-{i}') for i in range(300)]; sys.exit(1)\"",
        max_lines=60,
    )

    assert result["exit_code"] == 1
    stdout = result["stdout"]
    # The last line must be visible (line-299)
    assert "line-299" in stdout, f"tail not preserved for failing command; stdout tail:\n{stdout[-500:]}"


def test_shell_timeout_terminates_child_process_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atelier.gateway.adapters.mcp_server import _run_shell_tool

    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))

    result = _run_shell_tool(
        'python3 -c "import time; time.sleep(2)"',
        timeout=1,
    )
    time.sleep(1.5)

    assert result["exit_code"] == -1
    assert "timed out after 1s" in result["stderr"]


def test_shell_run_blocks_until_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atelier.gateway.adapters.mcp_server import _run_shell_tool

    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))

    # Foreground run blocks until the command finishes -- no artificial
    # window, no detach, no session, no poll -- even for a slow-ish command.
    result = _run_shell_tool(
        "python3 -c \"import time; time.sleep(2); print('done')\"",
        timeout=30,
    )
    assert result.get("status") != "running"
    assert "session_id" not in result
    assert result["exit_code"] == 0
    assert result["stdout"] == "done"


def test_shell_large_timeout_does_not_detach_fast_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atelier.gateway.adapters.mcp_server import _run_shell_tool

    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))

    # A 30-minute timeout budget must not make a fast command detach: it
    # blocks only as long as the command actually runs, then returns.
    result = _run_shell_tool("echo hi", timeout=1800)
    assert result.get("status") != "running"
    assert "session_id" not in result
    assert result["exit_code"] == 0
    assert result["stdout"] == "hi"


def test_shell_poll_blocks_until_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atelier.gateway.adapters.mcp_server import _run_shell_tool

    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))

    # Detach immediately, then a SINGLE blocking poll returns the finished
    # result -- no manual retry loop, no busy-polling.
    started = _run_shell_tool(
        "python3 -c \"import time; time.sleep(0.5); print('done')\"",
        timeout=10,
        background=True,
    )
    assert started["status"] == "running"

    completed = _run_shell_tool(session_id=started["session_id"], action="poll")
    assert completed["status"] == "completed"
    assert completed["exit_code"] == 0
    assert completed["stdout"] == "done"


def test_shell_background_return_reports_timeout_remaining(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atelier.gateway.adapters.mcp_server import _run_shell_tool

    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))

    # Detaching surfaces an honest upper bound (the timeout), not a fake ETA.
    started = _run_shell_tool(
        'python3 -c "import time; time.sleep(5)"',
        timeout=10,
        background=True,
    )
    try:
        assert started["status"] == "running"
        assert started["session_id"]
        assert started["duration_ms"] >= 0
        assert 0 < started["timeout_remaining_ms"] <= 10_000
    finally:
        _run_shell_tool(session_id=started["session_id"], action="cancel")


def test_render_shell_text_running_surfaces_progress_hints() -> None:
    from atelier.gateway.adapters.mcp_server import _render_shell_text

    text = _render_shell_text(
        {
            "status": "running",
            "session_id": "abc123",
            "pid": 42,
            "duration_ms": 95_000,
            "timeout_remaining_ms": 1_765_000,
        }
    )
    assert "status=running session_id=abc123" in text
    assert "pid=42" in text
    assert "elapsed=1m35s" in text
    assert "timeout_in=29m25s" in text


def test_shell_background_session_can_be_cancelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atelier.gateway.adapters.mcp_server import _run_shell_tool

    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))

    started = _run_shell_tool(
        'python3 -c "import time; time.sleep(10)"',
        timeout=10,
        background=True,
    )
    cancelled = _run_shell_tool(session_id=started["session_id"], action="cancel")
    time.sleep(0.1)

    assert cancelled["status"] == "cancelled"
    assert cancelled["exit_code"] == -1
    assert "cancelled" in cancelled["stderr"].lower()


def test_shell_background_session_enforces_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atelier.gateway.adapters.mcp_server import _run_shell_tool

    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))

    started = _run_shell_tool(
        'python3 -c "import time; time.sleep(2)"',
        timeout=1,
        background=True,
    )
    time.sleep(1.2)
    completed = _run_shell_tool(session_id=started["session_id"], action="poll")

    assert completed["status"] == "timed_out"
    assert completed["exit_code"] == -1
    assert "timed out after 1s" in completed["stderr"]


def test_shell_mcp_call_returns_managed_session_for_background_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))

    response = _call(
        "shell",
        {
            "command": 'python3 -c "import time; time.sleep(10)"',
            "timeout": 30,
            "background": True,
        },
    )
    text = response["result"]["content"][0]["text"]
    match = re.search(r"session_id=([a-f0-9]+)", text)

    assert "status=running" in text
    assert match is not None
    cancelled = mcp_server._run_shell_tool(session_id=match.group(1), action="cancel")
    assert cancelled["status"] == "cancelled"


def test_truncate_result_text_passes_small_through() -> None:
    small = "hello world"
    assert mcp_server._truncate_result_text(small, 1024) == small


def test_truncate_result_text_caps_oversized_with_notice() -> None:
    out = mcp_server._truncate_result_text("x" * 5000, 1024)
    assert len(out.encode("utf-8")) <= 1024
    assert "truncated" in out
    assert "5000 bytes total" in out


def test_truncate_result_text_keeps_valid_utf8_on_multibyte_boundary() -> None:
    # 'é' encodes to 2 bytes; an odd byte limit must not yield a partial char.
    out = mcp_server._truncate_result_text("é" * 1000, 101)
    out.encode("utf-8")  # raises if the head was split mid-codepoint


def test_write_jsonrpc_backstop_replaces_oversized_frame(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_server, "_MAX_WIRE_BYTES", 256)
    huge = {"jsonrpc": "2.0", "id": 7, "result": {"content": [{"type": "text", "text": "z" * 4000}]}}
    mcp_server._write_jsonrpc(huge)
    line = capsys.readouterr().out.strip()
    frame = json.loads(line)  # a single valid JSON-RPC line, not a 4 KB blob
    assert frame["id"] == 7
    assert "error" in frame
    assert len(line.encode("utf-8")) < 4000


def test_write_jsonrpc_passes_normal_frame_through(capsys: pytest.CaptureFixture[str]) -> None:
    msg = {"jsonrpc": "2.0", "id": 9, "result": {"content": [{"type": "text", "text": "ok"}]}}
    mcp_server._write_jsonrpc(msg)
    assert json.loads(capsys.readouterr().out.strip()) == msg


def test_read_oversized_result_is_capped_not_dropped(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: an exact (expand) read of a large file produced one >16 MiB
    # JSON-RPC frame, tripping the host stdout guard and disconnecting the
    # server. The result must be truncated in place, never dropped.
    _ = store_root
    monkeypatch.setenv("ATELIER_MCP_MAX_RESULT_BYTES", "70000")
    big = tmp_path / "big.txt"
    big.write_text("A" * 200_000, encoding="utf-8")
    text = _result(_call("read", {"path": str(big), "expand": True}))
    assert isinstance(text, str)
    assert len(text.encode("utf-8")) <= 70000
    assert "truncated" in text


def test_smart_read_single_caps_oversized_expand_at_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The source-side guard bounds an exact (expand) read of a huge file before
    # it is ever fully loaded, returning a truncated payload with the byte count.
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("ATELIER_MCP_MAX_RESULT_BYTES", "70000")
    big = tmp_path / "big.log"
    big.write_text("L" * 500_000, encoding="utf-8")
    payload = mcp_server._smart_read_single(str(big), expand=True)
    assert payload["truncated"] is True
    assert payload["bytes_total"] == 500_000
    assert len(payload["content"].encode("utf-8")) <= 70000


def test_render_memory_md_compact_recall() -> None:
    out = mcp_server._render_memory_md(
        {
            "passages": [
                {"id": "pas-1", "text": "Prefer atelier memory.", "source_ref": "sess#1", "tags": ["pref"]},
                {"id": "pas-2", "text": "Use uv run.", "source_ref": "sess#2", "tags": []},
            ]
        }
    )
    assert out is not None
    assert out.startswith("### memory (2 passage(s))")
    assert "- sess#1 [pref]" in out
    assert "Prefer atelier memory." in out
    # repeated JSON field keys are dropped
    assert "source_ref" not in out


def test_render_memory_md_non_recall_falls_back_to_json() -> None:
    # store_fact/vote_fact responses have no `passages` list -> keep JSON.
    assert mcp_server._render_memory_md({"id": "mem-1", "fact": "x"}) is None


def test_render_search_map_md_is_compact() -> None:
    out = mcp_server._render_search_md(
        {"mode": "map", "outline": "pkg/\n  mod.py", "ranked_files": ["pkg/mod.py"], "token_count": 10}
    )
    assert out is not None
    assert out.startswith("### repo_map")
    assert "pkg/mod.py" in out
    # the JSON wrapper / bookkeeping keys are gone
    assert "token_count" not in out
    assert "ranked_files" not in out


def test_check_auto_update_is_opt_in_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # Supply-chain guard (HIGH #8): startup auto-update must NOT run git/install
    # automatically. With ATELIER_AUTO_UPDATE unset it must short-circuit before
    # spawning any subprocess.
    monkeypatch.delenv("ATELIER_AUTO_UPDATE", raising=False)

    def _boom(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("auto-update ran a subprocess while opt-in env var was unset")

    import subprocess as _subprocess

    monkeypatch.setattr(_subprocess, "run", _boom)
    # Returns without touching subprocess.run.
    mcp_server._check_auto_update()
