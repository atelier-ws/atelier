from __future__ import annotations

from pathlib import Path

from atelier.core.capabilities.grounded_loop.grounding_evidence import (
    extract_grounding_targets,
    has_grounding_evidence,
    record_grounding_evidence,
)


def test_grounding_evidence_matches_normalized_paths_per_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    state = record_grounding_evidence(
        {"session_id": "session-a"},
        session_id="session-a",
        tool_name="read",
        targets=["src/app.py#10-20"],
        workspace_root=workspace,
    )

    assert has_grounding_evidence(state, session_id="session-a", target="src/app.py", workspace_root=workspace)
    assert not has_grounding_evidence(state, session_id="session-b", target="src/app.py", workspace_root=workspace)


def test_record_grounding_evidence_keeps_recent_bounded_entries(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state: dict[str, object] = {"session_id": "session-a"}

    for index in range(70):
        state = record_grounding_evidence(
            state,
            session_id="session-a",
            tool_name="read",
            targets=[f"src/file_{index}.py"],
            workspace_root=workspace,
        )

    evidence = state["grounding_evidence"]
    assert isinstance(evidence, list)
    assert len(evidence) == 64
    assert evidence[0]["path"] == "src/file_6.py"
    assert evidence[-1]["path"] == "src/file_69.py"


def test_extract_grounding_targets_recognizes_search_and_code_intel_shapes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert extract_grounding_targets(
        "search",
        args={},
        result={"matches": [{"path": "src/app.py"}], "ranked_files": ["src/other.py"]},
        workspace_root=workspace,
    ) == ["src/app.py", "src/other.py"]
    assert extract_grounding_targets(
        "symbols",
        args={},
        result={"symbols": [{"file_path": "src/app.py"}]},
        workspace_root=workspace,
    ) == ["src/app.py"]
