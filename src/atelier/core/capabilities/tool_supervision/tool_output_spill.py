"""Reversible spill store for oversized tool outputs.

The MCP dispatch path bounds a runaway tool result before it reaches the host
(head+tail compaction, then a hard byte ceiling). Historically the bytes the
ceiling drops are *lost*: a shell/sql/read/web_fetch result that overflows the
budget is truncated and the tail is gone, so the agent cannot recover it without
re-running the (often expensive, non-idempotent) tool.

This module generalizes the spill helper already used by ``native_search``
(``_spill_dir`` + ``_spill_response_payload``) into a standalone, reference-able
store: the full payload is written to disk under a content-addressed id and a
short ref id is handed back. ``retrieve(ref_id, slice=...)`` reads it back
(optionally a byte slice), so the dispatcher can return a summary plus a ref id
plus a recovery hint *instead of* discarding the overflow.

The spill directory is shared with ``native_search`` via ``ATELIER_MCP_SPILL_DIR``
(falling back to a temp dir), so a single env var controls where everything lands.

No network, no LLM, deterministic. Best-effort: a write failure returns ``None``
rather than breaking the tool call.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Prefix marking a spill ref id so callers / the retrieve op can recognize one.
SPILL_REF_PREFIX = "spill:"

# Bounded retention so the shared spill dir can't grow without limit across a long
# session or many sessions (nothing else ever deletes these files). The sweep runs
# best-effort on each write. Override via env; set either axis to 0 to disable it.
_DEFAULT_SPILL_MAX_FILES = 512
_DEFAULT_SPILL_TTL_SECONDS = 24 * 60 * 60  # 24h


def _spill_dir() -> Path:
    """Resolve the spill directory, mirroring ``native_search._spill_dir``.

    Honors ``ATELIER_MCP_SPILL_DIR`` so search spills and tool-output spills
    share one location; otherwise uses ``<tmp>/atelier-spill``.
    """
    configured = os.environ.get("ATELIER_MCP_SPILL_DIR")
    if configured:
        path = Path(configured).expanduser().resolve()
    else:
        path = Path(tempfile.gettempdir()) / "atelier-spill"
    path.mkdir(parents=True, exist_ok=True)
    # Spill payloads can contain command output, file contents, and SQL results,
    # so keep the directory owner-only. Best-effort: a shared/pre-existing dir we
    # don't own may reject chmod, which is fine.
    with contextlib.suppress(OSError):
        path.chmod(0o700)
    return path


def _ref_for(file_name: str) -> str:
    return f"{SPILL_REF_PREFIX}{file_name}"


def _path_for_ref(ref_id: str) -> Path | None:
    """Resolve a ref id to its on-disk path, rejecting path traversal."""
    name = ref_id[len(SPILL_REF_PREFIX) :] if ref_id.startswith(SPILL_REF_PREFIX) else ref_id
    # Reject anything that isn't a bare file name (no separators, no '..').
    if not name or name != Path(name).name:
        return None
    return _spill_dir() / name


def _retention_limits() -> tuple[int, int]:
    """Return ``(max_files, max_age_seconds)``; either ``<= 0`` disables that axis."""

    def _read(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return max(0, int(raw))
        except ValueError:
            return default

    return (
        _read("ATELIER_MCP_SPILL_MAX_FILES", _DEFAULT_SPILL_MAX_FILES),
        _read("ATELIER_MCP_SPILL_TTL_SECONDS", _DEFAULT_SPILL_TTL_SECONDS),
    )


def _enforce_retention(directory: Path) -> None:
    """Evict old spill artifacts by age then count so the dir stays bounded.

    Best-effort and never raises into the caller: retention is hygiene, not
    correctness. Sweeps every ``*.json`` in the shared spill dir (both
    tool-output and ``native_search`` spills, neither cleaned elsewhere).
    """
    max_files, max_age = _retention_limits()
    if max_files <= 0 and max_age <= 0:
        return
    try:
        entries: list[tuple[float, Path]] = []
        for p in directory.glob("*.json"):
            try:
                entries.append((p.stat().st_mtime, p))
            except OSError:
                continue
    except OSError:
        return
    now = time.time()
    survivors: list[tuple[float, Path]] = []
    for mtime, p in entries:
        if max_age > 0 and (now - mtime) > max_age:
            with contextlib.suppress(OSError):
                p.unlink()
        else:
            survivors.append((mtime, p))
    if max_files > 0 and len(survivors) > max_files:
        survivors.sort(key=lambda item: item[0])  # oldest first
        for _, p in survivors[: len(survivors) - max_files]:
            with contextlib.suppress(OSError):
                p.unlink()


@dataclass(frozen=True)
class SpillRecord:
    """A persisted spill: ref id + on-disk path + original byte size."""

    ref_id: str
    path: Path
    original_bytes: int


def spill(
    content: str,
    *,
    tool_name: str,
    kind: str = "tool_output",
    meta: dict[str, Any] | None = None,
) -> SpillRecord | None:
    """Persist the full ``content`` and return a referenceable record.

    The on-disk artifact is a JSON envelope so retrieve can return both the raw
    text and its provenance. Returns ``None`` on any write failure (best-effort;
    the caller falls back to the prior truncate/compact behavior).

    Args:
        content:   The full (oversized) tool output to preserve.
        tool_name: The tool that produced the output (for provenance + hints).
        kind:      Logical tag, e.g. ``tool_output`` (T7) or ``original`` (T8
                   pre-compaction snapshot, for reversibility).
        meta:      Optional extra provenance (query, path, byte budget, ...).
    """
    try:
        directory = _spill_dir()
        file_name = f"{kind}-{tool_name}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}.json"
        original_bytes = len(content.encode("utf-8"))
        envelope = {
            "tool": tool_name,
            "kind": kind,
            "created_at": time.time(),
            "original_bytes": original_bytes,
            "meta": meta or {},
            "content": content,
        }
        spill_path = directory / file_name
        # Atomic publish: write to a sibling temp file then rename, so a concurrent
        # retrieve never observes a half-written envelope. The '.tmp' suffix keeps
        # in-flight writes out of the '*.json' retention sweep.
        tmp_path = directory / f".{file_name}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            tmp_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_path, spill_path)
        finally:
            with contextlib.suppress(OSError):
                if tmp_path.exists():
                    tmp_path.unlink()
        _enforce_retention(directory)
        return SpillRecord(
            ref_id=_ref_for(file_name),
            path=spill_path,
            original_bytes=original_bytes,
        )
    except OSError:
        return None


def retrieve(ref_id: str, *, slice: tuple[int, int] | None = None) -> dict[str, Any]:
    """Read a spilled payload back by ref id.

    Args:
        ref_id: The id returned by :func:`spill` (``spill:<file>`` or bare file).
        slice:  Optional ``(start, length)`` character window into the content,
                so a caller can page through a huge payload without re-emitting
                all of it. ``length <= 0`` means "to the end".

    Returns a dict with the (possibly sliced) ``content`` and provenance, or an
    ``error`` key when the ref is unknown/unreadable.
    """
    path = _path_for_ref(ref_id)
    if path is None:
        return {"error": f"invalid spill ref id: {ref_id!r}", "ref_id": ref_id}
    if not path.exists():
        return {"error": f"spill ref not found (expired or never written): {ref_id!r}", "ref_id": ref_id}
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"could not read spill ref {ref_id!r}: {exc}", "ref_id": ref_id}
    if not isinstance(envelope, dict):
        # Valid JSON that isn't an object (e.g. an array/scalar left in the shared
        # spill dir by another producer) would make the .get() calls below raise;
        # return a structured error instead.
        return {"error": f"malformed spill envelope (not an object): {ref_id!r}", "ref_id": ref_id}

    content = str(envelope.get("content", ""))
    total_chars = len(content)
    sliced = content
    slice_info: dict[str, Any] | None = None
    if slice is not None:
        start, length = slice
        start = max(0, start)
        end = total_chars if length <= 0 else min(total_chars, start + length)
        sliced = content[start:end]
        slice_info = {"start": start, "end": end, "total_chars": total_chars}

    result: dict[str, Any] = {
        "ref_id": ref_id,
        "tool": envelope.get("tool"),
        "kind": envelope.get("kind"),
        "original_bytes": envelope.get("original_bytes"),
        "meta": envelope.get("meta", {}),
        "content": sliced,
        "total_chars": total_chars,
    }
    if slice_info is not None:
        result["slice"] = slice_info
    return result


def summary_with_ref(
    summary: str,
    record: SpillRecord,
    *,
    tool_name: str,
    retrieve_op: str = "compact",
    max_chars: int | None = None,
) -> str:
    """Compose the host-facing text: summary + ref id + a retrieve hint.

    The hint names the agent-callable retrieve path so the model knows how to
    pull the full (or a sliced) payload back instead of re-running ``tool_name``.
    """
    hint = (
        f"\n\n[atelier: full {tool_name} output ({record.original_bytes} bytes) "
        f"spilled to ref {record.ref_id}; recover it with the `{retrieve_op}` tool "
        f'(op="retrieve", ref_id="{record.ref_id}"), or a window via '
        f"slice_start/slice_length, instead of re-running {tool_name}.]"
    )
    if max_chars is None:
        return f"{summary}{hint}"
    if max_chars <= 0:
        return ""
    if len(hint) >= max_chars:
        # The cap is smaller than the full recovery hint (only reachable via an
        # impractically tiny configured limit). Never cut mid-ref: prefer the bare
        # ref_id so the spill stays recoverable, falling back to its prefix only
        # when even that can't fit. Always honor the promised return bound.
        ref = record.ref_id
        return ref if len(ref) <= max_chars else ref[:max_chars]

    available = max_chars - len(hint)
    if len(summary) > available:
        marker = "\n...[summary clipped; full output is in spill]...\n"
        if available <= len(marker):
            summary = summary[:available]
        else:
            content_budget = available - len(marker)
            head_chars = int(content_budget * 0.7)
            tail_chars = content_budget - head_chars
            summary = f"{summary[:head_chars]}{marker}{summary[-tail_chars:]}"
    return f"{summary}{hint}"
