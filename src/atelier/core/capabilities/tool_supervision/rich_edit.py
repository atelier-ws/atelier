"""Atelier-native rich batch edit capability."""

from __future__ import annotations

import ast
import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atelier.core.capabilities.source_projection import (
    MinifiedEditError,
    ProjectionEditError,
    ProjectionMapping,
    apply_compact_projection_edit,
    apply_compact_projection_edits,
    apply_minified_edit,
    language_for_minify,
)

from . import command_discipline
from .fuzzy_match import apply_fuzzy_replace, normalize_for_fuzzy
from .path_safety import PROTECTED_PARTS
from .symbol_edit import SymbolEditError, record_symbol_edit_memory, resolve_symbol_edit

logger = logging.getLogger(__name__)

_SMART_QUOTES = str.maketrans(
    {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'", "\u2013": "-", "\u2014": "-"}
)


@dataclass(frozen=True)
class TargetSpec:
    path: str
    start_line: int | None = None
    end_line: int | None = None
    cell: str | int | None = None


def _repo_root(repo_root: str | Path | None = None) -> Path:
    return Path(repo_root or Path.cwd()).resolve()


def _parse_target(raw_path: str) -> TargetSpec:
    if "#cell=" in raw_path:
        path, cell = raw_path.split("#cell=", 1)
        return TargetSpec(path=path, cell=cell)
    match = re.search(r"#(\d+)(?:-(\d+))?$", raw_path)
    if match:
        return TargetSpec(
            path=raw_path[: match.start()],
            start_line=int(match.group(1)),
            end_line=int(match.group(2) or match.group(1)),
        )
    return TargetSpec(path=raw_path)


def _resolve(root: Path, raw_path: str, allowed_roots: list[Path] | None = None) -> Path:
    spec = _parse_target(raw_path)
    path = Path(spec.path)
    resolved = path if path.is_absolute() else root / path
    resolved = resolved.resolve()
    roots = [root, *(allowed_roots or [])]
    if not any(resolved == r or resolved.is_relative_to(r) for r in roots):
        raise ValueError(
            f"path escape denied: {raw_path} is outside the workspace root {root} — "
            "use the host's native tools for files outside the workspace"
        )
    if any(part in PROTECTED_PARTS for part in resolved.parts):
        raise ValueError(f"protected path denied: {raw_path}")
    return resolved


def _normalize_typography(text: str) -> str:
    return text.translate(_SMART_QUOTES)


_ALL_WS = re.compile(r"\s+")
_TRAILING_COMMA_BEFORE_CLOSER = re.compile(r",([)\]\}])")
# Minimum stripped length before a contained new_string counts as "already
# applied" — guards against trivially short coincidental matches.
_REFORMAT_NOOP_MIN_CHARS = 24


def _strip_formatting(text: str) -> str:
    """Strip all whitespace and trailing commas so formatter rewraps compare equal."""
    return _TRAILING_COMMA_BEFORE_CLOSER.sub(r"\1", _ALL_WS.sub("", text))


def _placeholder_pattern(old_string: str) -> re.Pattern[str] | None:
    if "..." not in old_string and "<...>" not in old_string:
        return None
    escaped = re.escape(old_string)
    escaped = escaped.replace(re.escape("<...>"), r"[\s\S]{0,4000}").replace(re.escape("..."), r"[\s\S]{0,2000}")
    return re.compile(escaped)


def _leading_whitespace(line: str) -> str:
    match = re.match(r"\s*", line)
    return match.group(0) if match else ""


def _adapt_indentation(old: str, new: str, matched: str) -> str:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    matched_lines = matched.splitlines()
    if len(new_lines) <= 1 or not old_lines or not matched_lines:
        return new
    trailing_newline = "\n" if new.endswith("\n") else ""
    base_indent_text = _leading_whitespace(matched_lines[0]) if matched_lines else ""
    if not base_indent_text and len(old_lines) > 1:
        base_indent_text = _leading_whitespace(old_lines[1])
    if base_indent_text:
        result: list[str] = [new_lines[0]]
        consecutive_blanks = 0
        for line in new_lines[1:]:
            if not line.strip():
                consecutive_blanks += 1
                result.append(line)
            elif not line.startswith((" ", "\t")) and consecutive_blanks < 2:
                result.append(base_indent_text + line)
                consecutive_blanks = 0
            else:
                result.append(line)
                consecutive_blanks = 0
        new_lines = result
    old_indent = len(old_lines[0]) - len(old_lines[0].lstrip())
    matched_indent = len(matched_lines[0]) - len(matched_lines[0].lstrip())
    delta = matched_indent - old_indent
    if delta <= 0:
        return "\n".join(new_lines) + trailing_newline
    prefix = " " * delta
    return "\n".join((prefix + line if line.strip() else line) for line in new_lines) + trailing_newline


def _replace_in_scope(content: str, spec: TargetSpec, old_string: str, new_string: str) -> tuple[str, int, int, str]:
    """Replace old_string with new_string, returning (new_content, line_start, line_end, match_mode).

    match_mode is one of: "noop", "exact", "normalized", "placeholder", "fuzzy".
    Raises ValueError when the string cannot be located with sufficient confidence.
    """
    lines = content.splitlines(keepends=True)
    start_offset = 0
    end_offset = len(content)
    if spec.start_line is not None:
        start = max(1, spec.start_line)
        end = min(len(lines), spec.end_line or start)
        start_offset = sum(len(line) for line in lines[: start - 1])
        end_offset = sum(len(line) for line in lines[:end])
    scoped = content[start_offset:end_offset]

    index = scoped.find(old_string)
    matched = old_string
    match_mode = "exact"
    if index != -1 and old_string and scoped.count(old_string) > 1:
        raise ValueError(
            "old_string is not unique within the resolved scope; add surrounding context to identify a single match"
        )
    if index == -1:
        normalized_content = _normalize_typography(scoped)
        normalized_old = _normalize_typography(old_string)
        normalized_index = normalized_content.find(normalized_old)
        if normalized_index != -1:
            index = normalized_index
            matched = scoped[index : index + len(old_string)]
            match_mode = "normalized"
    if index == -1:
        placeholder = _placeholder_pattern(old_string)
        if placeholder:
            match = placeholder.search(scoped)
            if match:
                index = match.start()
                matched = match.group(0)
                match_mode = "placeholder"
    if index != -1:
        # Exact matches replace verbatim: the caller's new_string is authoritative.
        # Indentation adaptation is only a courtesy for whitespace-divergent matches
        # (normalized/placeholder/fuzzy). Applying it to an exact match whose anchor
        # begins inside an indented block wrongly re-indents replacement lines that
        # legitimately dedent (e.g. a module-level constant inserted after a list
        # literal), turning a valid edit into a SyntaxError.
        if match_mode == "exact":
            replacement = new_string
        else:
            replacement = _adapt_indentation(old_string, new_string, matched)
        absolute = start_offset + index
        line_start = content[:absolute].count("\n") + 1
        line_end = line_start + matched.count("\n")
        return (
            content[:absolute] + replacement + content[absolute + len(matched) :],
            line_start,
            line_end,
            match_mode,
        )

    # Idempotency fallback: every locate rung missed old_string, but the edit
    # may simply have been applied already (stale retry).
    if old_string and new_string and new_string in scoped:
        idx = scoped.find(new_string)
        absolute = start_offset + idx
        line_start = content[:absolute].count("\n") + 1
        line_end = line_start + new_string.count("\n")
        return content, line_start, line_end, "noop"

    # Formatter-tolerant variant: a post-edit formatter may have rewrapped the
    # previously applied new_string, so compare with all whitespace stripped.
    if old_string and new_string:
        flat_new = _strip_formatting(new_string)
        if len(flat_new) >= _REFORMAT_NOOP_MIN_CHARS and flat_new in _strip_formatting(scoped):
            line = spec.start_line or 1
            return content, line, line, "noop"

    # Minified-projection fallback: old_string may have been copied from a
    # minified read view (comments and blank lines stripped, inline
    # whitespace collapsed). Re-minify the live file, match in minified space,
    # then splice back onto the untransformed source. Skipped for line-scoped
    # edits, whose disk line numbers are authoritative.
    if spec.start_line is None:
        minify_lang = language_for_minify(spec.path)
        if minify_lang is not None:
            try:
                minified_content, minified_start, minified_end = apply_minified_edit(
                    content, minify_lang, old_string, new_string, path=spec.path
                )
            except MinifiedEditError:
                pass
            else:
                return minified_content, minified_start, minified_end, "minified"

    if normalize_for_fuzzy(old_string):
        fuzzed, line_start, line_end = apply_fuzzy_replace(scoped, old_string, new_string)
        return (
            content[:start_offset] + fuzzed + content[end_offset:],
            line_start + content[:start_offset].count("\n"),
            line_end + content[:start_offset].count("\n"),
            "fuzzy",
        )
    raise ValueError("old_string not found in file")


def _cell_index(cells: list[dict[str, Any]], target: str | int | None) -> int:
    if target is None:
        raise ValueError("notebook cell target is required")
    if target == "last":
        return len(cells) - 1
    index = int(target)
    if index < 0 or index >= len(cells):
        raise ValueError("notebook cell target out of range")
    return index


def _cell_source(cell: dict[str, Any]) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else str(source)


def _set_cell_source(cell: dict[str, Any], source: str) -> None:
    cell["source"] = source
    if cell.get("cell_type") == "code":
        cell["outputs"] = []
        cell["execution_count"] = None


def _apply_notebook_edit(notebook: dict[str, Any], spec: TargetSpec, edit: dict[str, Any]) -> None:
    cells = notebook.setdefault("cells", [])
    if not isinstance(cells, list):
        raise ValueError("notebook cells must be a list")
    action = edit.get("cell_action")
    if action in {"insert_after", "insert_before"}:
        index = _cell_index(cells, spec.cell)
        new_cell = {
            "cell_type": edit.get("cell_type", "code"),
            "metadata": {},
            "source": edit.get("new_string", ""),
        }
        if new_cell["cell_type"] == "code":
            new_cell.update({"outputs": [], "execution_count": None})
        cells.insert(index + (1 if action == "insert_after" else 0), new_cell)
        return
    if action == "delete":
        del cells[_cell_index(cells, spec.cell)]
        return
    if action in {"move_after", "move_before"}:
        index = _cell_index(cells, spec.cell)
        target = _cell_index(cells, edit.get("cell_move_target"))
        cell = cells.pop(index)
        if index < target:
            target -= 1
        cells.insert(target + (1 if action == "move_after" else 0), cell)
        return
    if edit.get("overwrite") and spec.cell is not None:
        index = _cell_index(cells, spec.cell)
        try:
            replacement = json.loads(str(edit.get("new_string", "")))
            if isinstance(replacement, dict) and "cell_type" in replacement:
                cells[index] = replacement
                return
        except Exception:
            logging.exception("Recovered from broad exception handler")
            logger.warning(
                "Suppressed exception at rich_edit.py:215",
                exc_info=True,
            )
        _set_cell_source(cells[index], str(edit.get("new_string", "")))
        return
    matches = [cell for cell in cells if str(edit.get("old_string", "")) in _cell_source(cell)]
    if len(matches) != 1:
        raise ValueError("old_string must match exactly one notebook cell")
    cell = matches[0]
    _set_cell_source(
        cell,
        _cell_source(cell).replace(str(edit.get("old_string", "")), str(edit.get("new_string", "")), 1),
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    if path.exists():
        # tmp.replace() discards the destination's metadata, stripping the exec
        # bit from scripts/hooks. Carry the original mode (and other stat) over.
        with contextlib.suppress(OSError):
            shutil.copystat(path, tmp)
            os.chmod(tmp, os.stat(path).st_mode)
    tmp.replace(path)


def _build_retry_hint(
    root: Path,
    backups: dict[Path, bytes | None],
    edit: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a retry_with hint so the caller can retry without a separate re-read turn.

    Sources the failing edit's own file (pre-edit backup when available, disk
    otherwise), locates the unique line containing the first non-blank line of
    old_string, and ships that exact region back so the model can correct
    old_string inline.
    """
    if not edit:
        return None
    old_string = str(edit.get("old_string") or "")
    raw_path = str(edit.get("file_path") or edit.get("path") or "")
    if not old_string or not raw_path:
        return None
    try:
        path = _resolve(root, raw_path)
    except Exception:  # noqa: BLE001 — hint is best-effort
        return None

    payload = backups.get(path)
    if payload is not None:
        try:
            disk_content = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    else:
        try:
            disk_content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    # Already-applied detection against the whole file: a line-scoped edit may
    # miss content that a formatter moved or rewrapped outside the scope.
    new_string = str(edit.get("new_string") or "")
    if new_string:
        flat_new = _strip_formatting(new_string)
        if len(flat_new) >= _REFORMAT_NOOP_MIN_CHARS and flat_new in _strip_formatting(disk_content):
            return {
                "already_applied": True,
                "hint": (
                    "edit appears already applied — the file already contains new_string "
                    "(possibly reformatted); do not retry this edit"
                ),
            }

    old_lines = old_string.splitlines()
    first_anchor = next((line.strip() for line in old_lines if line.strip()), None)
    if not first_anchor:
        return None

    disk_lines = disk_content.splitlines(keepends=True)
    anchor_positions = [i for i, line in enumerate(disk_lines) if first_anchor in line]
    if len(anchor_positions) != 1:
        return None
    # Unique anchor — extract a window the same size as old_string ± 2 lines
    n_lines = max(len(old_lines), 1)
    start = anchor_positions[0]
    end = min(len(disk_lines), start + n_lines + 2)
    excerpt = "".join(disk_lines[start:end])
    clean_path = raw_path.split("#")[0]
    return {
        "path": f"{clean_path}#L{start + 1}-{end}",
        "old_string": excerpt,
        "hint": "exact disk content at nearest anchor — replace old_string with this",
    }


def _parse_gate_message(
    path: Path,
    new_content: str,
    parse_err: SyntaxError,
    applied: list[dict[str, Any]],
) -> str:
    """Build an actionable parse-gate error with the broken region inline.

    Without the snippet agents retry the identical edit (the failure is in the
    would-be content they never see), then defect to shell-based writes.
    """
    lineno = parse_err.lineno or 1
    lines = new_content.splitlines()
    lo = max(0, lineno - 6)
    hi = min(len(lines), lineno + 5)
    snippet = "\n".join(f"{i + 1}: {lines[i]}" for i in range(lo, hi))
    fuzzy_note = ""
    for entry in applied:
        entry_path = str(entry.get("path", "")).split("#")[0]
        mode = entry.get("match_mode")
        if entry_path.endswith(path.name) and mode in ("normalized", "placeholder", "fuzzy"):
            fuzzy_note = (
                f" (old_string matched via {mode} mode — it may have anchored at the"
                " wrong spot or covered less text than intended)"
            )
            break
    return (
        f"post-edit parse error in {path.name} at line {lineno}: {parse_err.msg}"
        f" — edit rolled back{fuzzy_note}. Would-be content around the error:\n{snippet}\n"
        "Do NOT resend the same edit. Extend old_string to cover the full region you are"
        " replacing (e.g. the entire block through its closing brace); scope with"
        ' "file.py#start-end" to disambiguate, or rewrite the whole file with overwrite=true.'
    )


def apply_rich_edits(
    edits: list[dict[str, Any]],
    *,
    repo_root: str | Path | None = None,
    atomic: bool = True,
    allowed_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """Apply rich Atelier edits in memory, writing each touched file once."""
    root = _repo_root(repo_root)
    backups: dict[Path, bytes | None] = {}
    file_state: dict[Path, str] = {}
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    resolved_symbol_edits = []
    _current_edit: dict[str, Any] | None = None  # tracks the edit in-flight for error hints

    try:
        for edit in edits:
            _current_edit = edit
            if str(edit.get("kind") or "") == "symbol":
                resolved = resolve_symbol_edit(edit, repo_root=root)
                resolved_symbol_edits.append(resolved)
                edit = {
                    "file_path": resolved.scoped_file_path,
                    "old_string": resolved.old_string,
                    "new_string": resolved.new_string,
                }
                raw_path = resolved.scoped_file_path
            else:
                raw_path = str(edit.get("file_path") or edit.get("path") or "")
            if not raw_path:
                raise ValueError("file_path is required")
            spec = _parse_target(raw_path)
            path = _resolve(root, raw_path, allowed_roots=allowed_roots)
            if path not in backups:
                backups[path] = path.read_bytes() if path.exists() else None
            content = file_state.get(path)
            if content is None:
                content = path.read_text(encoding="utf-8") if path.exists() else ""

            if path.suffix.lower() == ".ipynb":
                notebook = json.loads(content or '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
                _apply_notebook_edit(notebook, spec, edit)
                file_state[path] = json.dumps(notebook, indent=2)
                applied.append({"path": raw_path, "kind": "notebook"})
                continue

            if str(edit.get("kind") or "") == "projection":
                raw_mapping = edit.get("projection_mapping")
                if not isinstance(raw_mapping, dict):
                    raise ProjectionEditError(
                        "projection_mapping is required for projection edits",
                        code="missing_projection_mapping",
                        hint="Pass the projection_mapping returned by a compact read with include_meta=true.",
                    )
                mapping = ProjectionMapping.from_dict(raw_mapping)
                mapping_path = Path(mapping.path).resolve() if mapping.path else path
                if mapping.path and mapping_path != path:
                    raise ProjectionEditError(
                        "projection_mapping path does not match file_path",
                        code="projection_path_mismatch",
                        hint="Use the same file_path that produced the compact projection.",
                    )
                projected_ranges = edit.get("projected_ranges")
                if isinstance(projected_ranges, list) and projected_ranges:
                    new_content, hunks = apply_compact_projection_edits(
                        content,
                        mapping=mapping,
                        projected_edits=[
                            {
                                "projected_start": int(item.get("projected_start", 0)),
                                "projected_end": int(item.get("projected_end", 0)),
                                "new_string": str(item.get("new_string", "")),
                            }
                            for item in projected_ranges
                            if isinstance(item, dict)
                        ],
                    )
                else:
                    if not {
                        "projected_start",
                        "projected_end",
                        "new_string",
                    }.issubset(edit):
                        raise ProjectionEditError(
                            "projection edit must provide projected_start/projected_end/new_string or projected_ranges",
                            code="missing_projection_span",
                            hint="Pass a single exact projected span or a non-empty projected_ranges array.",
                        )
                    new_content, line_start, line_end = apply_compact_projection_edit(
                        content,
                        mapping=mapping,
                        projected_start=int(edit.get("projected_start", 0)),
                        projected_end=int(edit.get("projected_end", 0)),
                        new_string=str(edit.get("new_string", "")),
                    )
                    hunks = [(line_start, line_end)]
                file_state[path] = new_content
                applied.append(
                    {
                        "path": raw_path,
                        "kind": "projection",
                        "projection_kind": mapping.projection_kind,
                        "hunks": [{"line_start": line_start, "line_end": line_end} for line_start, line_end in hunks],
                    }
                )
                continue

            if edit.get("overwrite") or (not path.exists() and not edit.get("old_string")):
                file_state[path] = str(edit.get("new_string", ""))
                applied.append({"path": raw_path, "kind": "overwrite"})
                continue

            old_string = str(edit.get("old_string", ""))
            if not old_string:
                raise ValueError("old_string is required unless overwrite=true or creating a new file")
            new_content, line_start, line_end, match_mode = _replace_in_scope(
                content, spec, old_string, str(edit.get("new_string", ""))
            )
            file_state[path] = new_content
            applied_entry: dict[str, Any] = {
                "path": raw_path,
                "hunks": [{"line_start": line_start, "line_end": line_end}],
                "match_mode": match_mode,
            }
            if match_mode == "noop":
                applied_entry["already_applied"] = True
            if resolved_symbol_edits and raw_path == resolved_symbol_edits[-1].scoped_file_path:
                applied_entry["kind"] = "symbol"
                applied_entry["symbol_id"] = resolved_symbol_edits[-1].symbol_id
            applied.append(applied_entry)

        # Parse gate: verify every touched Python file compiles before writing.
        # This catches structural corruption (e.g. a fuzzy match that ate a
        # neighboring function) without requiring a separate lint turn.
        for path, new_content in file_state.items():
            if path.suffix == ".py":
                try:
                    ast.parse(new_content)
                except SyntaxError as parse_err:
                    raise ValueError(_parse_gate_message(path, new_content, parse_err, applied)) from parse_err

        for path, content in file_state.items():
            _atomic_write(path, content)
        if file_state:
            command_discipline.note_workspace_changed()
        if resolved_symbol_edits:
            from atelier.core.capabilities.code_context import CodeContextEngine

            engine = CodeContextEngine(root)
            engine._reindex_files([item.repo_file_path for item in resolved_symbol_edits])
            for resolved in resolved_symbol_edits:
                record_symbol_edit_memory(resolved)
        return {"applied": applied, "failed": [], "rolled_back": False, "writes": len(file_state)}
    except Exception as exc:
        logging.exception("Recovered from broad exception handler")
        if isinstance(exc, SymbolEditError | ProjectionEditError):
            failed.append(exc.to_dict())
        else:
            err: dict[str, Any] = {"error": str(exc)}
            # Rich retry hint: when old_string wasn't found, ship the nearest
            # disk region so the follow-up edit doesn't need a re-read turn.
            if "old_string not found" in str(exc) or "not found in file" in str(exc):
                hint = _build_retry_hint(root, backups, _current_edit)
                if hint and hint.get("already_applied"):
                    err["already_applied"] = True
                    err["hint"] = hint["hint"]
                elif hint:
                    err["retry_with"] = hint
            failed.append(err)
        if atomic:
            for path, payload in backups.items():
                if payload is None:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)
            envelope: dict[str, Any] = {"applied": [], "failed": failed, "rolled_back": True}
            already = [str(entry.get("path")) for entry in applied if entry.get("already_applied")]
            if already:
                envelope["already_applied"] = already
                envelope["note"] = "already_applied edits were found on disk pre-rollback and remain in effect"
            return envelope
        for path, content in file_state.items():
            with contextlib.suppress(Exception):
                _atomic_write(path, content)
        return {
            "applied": applied,
            "failed": failed,
            "rolled_back": False,
            "writes": len(file_state),
        }


__all__ = ["apply_rich_edits"]
