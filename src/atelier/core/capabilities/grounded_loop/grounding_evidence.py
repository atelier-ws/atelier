from __future__ import annotations

import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GROUNDING_EVIDENCE_KEY = "grounding_evidence"
MAX_GROUNDING_EVIDENCE = 64
_ANCHOR_PATTERN = re.compile(r"#\d+(?:-\d+)?$")
_CODE_INTEL_TOOLS = frozenset({"symbols", "node", "explore", "callers", "callees", "usages", "impact"})


def _workspace_root(workspace_root: str | Path | None) -> Path:
    return Path(workspace_root or os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd()).resolve()


def normalize_grounding_target(target: str, *, workspace_root: str | Path | None = None) -> str:
    raw = str(target or "").strip()
    if not raw:
        return ""
    if "#cell=" in raw:
        raw = raw.split("#cell=", 1)[0]
    else:
        match = _ANCHOR_PATTERN.search(raw)
        if match:
            raw = raw[: match.start()]
    root = _workspace_root(workspace_root)
    candidate = Path(raw)
    resolved = candidate if candidate.is_absolute() else root / candidate
    resolved = resolved.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def _normalize_evidence_entries(raw_entries: Any, *, workspace_root: str | Path | None = None) -> list[dict[str, str]]:
    if not isinstance(raw_entries, list):
        return []
    entries: list[dict[str, str]] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("session_id") or "").strip()
        tool = str(item.get("tool") or "").strip()
        path = normalize_grounding_target(str(item.get("path") or ""), workspace_root=workspace_root)
        recorded_at = str(item.get("recorded_at") or "").strip()
        if session_id and tool and path and recorded_at:
            entries.append(
                {
                    "session_id": session_id,
                    "tool": tool,
                    "path": path,
                    "recorded_at": recorded_at,
                }
            )
    return entries


def record_grounding_evidence(
    state: dict[str, Any],
    *,
    session_id: str,
    tool_name: str,
    targets: Iterable[str],
    workspace_root: str | Path | None = None,
    recorded_at: str | None = None,
    max_entries: int = MAX_GROUNDING_EVIDENCE,
) -> dict[str, Any]:
    normalized_targets = [
        normalized
        for normalized in (normalize_grounding_target(target, workspace_root=workspace_root) for target in targets)
        if normalized
    ]
    if not session_id or not normalized_targets:
        return dict(state)

    prior_entries = _normalize_evidence_entries(state.get(GROUNDING_EVIDENCE_KEY), workspace_root=workspace_root)
    entry_time = recorded_at or datetime.now(UTC).isoformat()
    new_keys = {(session_id, tool_name, path) for path in normalized_targets}
    kept_entries = [
        entry for entry in prior_entries if (entry["session_id"], entry["tool"], entry["path"]) not in new_keys
    ]
    kept_entries.extend(
        {
            "session_id": session_id,
            "tool": tool_name,
            "path": path,
            "recorded_at": entry_time,
        }
        for path in normalized_targets
    )
    updated = dict(state)
    updated[GROUNDING_EVIDENCE_KEY] = kept_entries[-max_entries:]
    return updated


def has_grounding_evidence(
    state: dict[str, Any],
    *,
    session_id: str,
    target: str,
    workspace_root: str | Path | None = None,
) -> bool:
    normalized_target = normalize_grounding_target(target, workspace_root=workspace_root)
    if not session_id or not normalized_target:
        return False
    return any(
        entry["session_id"] == session_id and entry["path"] == normalized_target
        for entry in _normalize_evidence_entries(state.get(GROUNDING_EVIDENCE_KEY), workspace_root=workspace_root)
    )


def missing_grounding_targets(
    state: dict[str, Any],
    *,
    session_id: str,
    targets: Iterable[str],
    workspace_root: str | Path | None = None,
) -> list[str]:
    normalized_targets = [
        normalized
        for normalized in (normalize_grounding_target(target, workspace_root=workspace_root) for target in targets)
        if normalized
    ]
    return [
        target
        for target in normalized_targets
        if not has_grounding_evidence(state, session_id=session_id, target=target, workspace_root=workspace_root)
    ]


def _extract_paths(value: Any) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key in ("path", "file_path", "file"):
            path = value.get(key)
            if isinstance(path, str) and path:
                paths.append(path)
        for nested in value.values():
            paths.extend(_extract_paths(nested))
        return paths
    if isinstance(value, list):
        for item in value:
            paths.extend(_extract_paths(item))
    return paths


def extract_grounding_targets(
    tool_name: str,
    *,
    args: dict[str, Any],
    result: dict[str, Any],
    workspace_root: str | Path | None = None,
) -> list[str]:
    lowered = tool_name.lower().strip()
    candidates: list[str] = []
    if lowered == "read":
        for value in (args.get("path"), result.get("path")):
            if isinstance(value, str) and value:
                candidates.append(value)
    elif lowered == "grep":
        candidates.extend(_extract_paths(result.get("matches")))
    elif lowered == "search":
        candidates.extend(_extract_paths(result.get("matches")))
        ranked_files = result.get("ranked_files")
        if isinstance(ranked_files, list):
            candidates.extend(path for path in ranked_files if isinstance(path, str) and path)
    elif lowered == "context":
        if str(args.get("mode") or "").strip() != "symbols":
            return []
        files = args.get("files")
        if isinstance(files, list):
            candidates.extend(path for path in files if isinstance(path, str) and path)
    elif lowered in _CODE_INTEL_TOOLS:
        candidates.extend(_extract_paths(result))

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        path = normalize_grounding_target(candidate, workspace_root=workspace_root)
        if path and path not in seen:
            seen.add(path)
            normalized.append(path)
    return normalized


def extract_edit_targets(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    workspace_root: str | Path | None = None,
) -> list[str]:
    lowered = tool_name.lower().strip()
    candidates: list[str] = []
    if lowered == "multiedit":
        edits = tool_input.get("edits")
        if isinstance(edits, list):
            for edit in edits:
                if not isinstance(edit, dict):
                    continue
                target = edit.get("file_path") or edit.get("path") or edit.get("filename")
                if isinstance(target, str) and target:
                    candidates.append(target)
    else:
        target = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("filename")
        if isinstance(target, str) and target:
            candidates.append(target)

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        path = normalize_grounding_target(candidate, workspace_root=workspace_root)
        if path and path not in seen:
            seen.add(path)
            normalized.append(path)
    return normalized


__all__ = [
    "GROUNDING_EVIDENCE_KEY",
    "MAX_GROUNDING_EVIDENCE",
    "extract_edit_targets",
    "extract_grounding_targets",
    "has_grounding_evidence",
    "missing_grounding_targets",
    "normalize_grounding_target",
    "record_grounding_evidence",
]
