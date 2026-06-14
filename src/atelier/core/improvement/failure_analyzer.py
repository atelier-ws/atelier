"""Cluster failed runs into FailureCluster objects.

Input: persisted run ledger snapshots (dicts) from ``<root>/sessions/<id>/run.json``.
Output: ``list[FailureCluster]`` ranked by frequency x severity.

Fingerprint rules:
  - take the last error_signature on each failed run
  - if absent, take the last high-severity monitor alert
  - if absent, take the run status itself

Cluster key: (environment_id, fingerprint).
"""

from __future__ import annotations

import json
import re
import shlex
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from atelier.core.capabilities.lesson_promotion import LessonPromoterCapability
from atelier.core.foundation.models import FailureCluster
from atelier.core.foundation.store import ContextStore


def _normalize_signal(text: str) -> str | None:
    line = str(text or "").strip().splitlines()[0].strip() if text else ""
    if not line:
        return None
    return line[:200]


_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_FAILURE_HINT_RE = re.compile(
    r"\b(error|failed|failure|exception|timeout|forbidden|denied|unauthorized)\b", re.IGNORECASE
)
_LOW_VALUE_COMMANDS = {
    "[",
    "awk",
    "bun",
    "cat",
    "cd",
    "echo",
    "find",
    "grep",
    "head",
    "ls",
    "nl",
    "node",
    "npm",
    "pip",
    "pip3",
    "pnpm",
    "printf",
    "pwd",
    "python",
    "python3",
    "rg",
    "sed",
    "tail",
    "test",
    "true",
    "false",
    "uv",
    "wc",
    "xargs",
    "yarn",
}


def _normalize_command_name(command_text: str) -> str:
    text = str(command_text or "").strip()
    if not text:
        return "unknown_command"
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    if not tokens:
        return "unknown_command"

    filtered: list[str] = []
    for token in tokens:
        tok = token.strip()
        if not tok:
            continue
        if _ASSIGNMENT_RE.match(tok):
            continue
        filtered.append(tok)

    if not filtered:
        return "unknown_command"

    command = filtered[0]
    if command in {"env", "sudo"} and len(filtered) > 1:
        command = filtered[1]
    if command in {"bash", "sh", "zsh"} and len(filtered) > 1:
        idx = 1
        while idx < len(filtered) and str(filtered[idx]).startswith("-"):
            idx += 1
        if idx < len(filtered):
            inner = str(filtered[idx]).strip()
            if inner:
                command = inner.split()[0]

    command = command.split("/")[-1]
    command = command.lstrip("./")
    return command or "unknown_command"


def _tool_failure_fingerprint(snapshot: dict[str, Any]) -> str | None:
    for tool in reversed(snapshot.get("tools_called", []) or []):
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name", "")).strip() or "unknown_tool"
        summary = _normalize_signal(str(tool.get("result_summary", "")).strip())
        if summary and _FAILURE_HINT_RE.search(summary):
            return f"tool_failure:{name}:{summary[:120]}"
    return None


def _validation_failure_fingerprint(snapshot: dict[str, Any]) -> str | None:
    for vr in reversed(snapshot.get("validation_results", []) or []):
        if not isinstance(vr, dict):
            continue
        passed = vr.get("passed")
        if passed is False:
            name = str(vr.get("name", "")).strip() or "unknown_validation"
            detail = _normalize_signal(str(vr.get("detail", "")).strip() or "failed") or ""
            return f"validation_failed:{name}:{detail[:120]}"
    return None


def _fingerprint(snapshot: dict[str, Any]) -> str | None:
    events = snapshot.get("events", [])
    last_error = None
    last_high_alert = None
    for event in events:
        kind = event.get("kind")
        payload = event.get("payload") or {}
        if kind == "command_result" and not payload.get("ok"):
            sig = str(payload.get("error_signature", "")).strip()
            if sig:
                last_error = sig
        elif kind == "watchdog_alert" and payload.get("severity") == "high":
            last_high_alert = str(event.get("summary", "")).strip() or None
    if last_error:
        return last_error
    if last_high_alert:
        return last_high_alert

    repeated = snapshot.get("repeated_failures", []) or []
    for item in reversed(repeated):
        sig = _normalize_signal((item or {}).get("signature", "")) or ""
        if sig:
            return sig

    for err in reversed(snapshot.get("errors_seen", []) or []):
        sig = _normalize_signal(err) or ""
        if sig:
            return sig

    for cmd in reversed(snapshot.get("commands_run", []) or []):
        if isinstance(cmd, dict):
            exit_code = cmd.get("exit_code")
            command_name = _normalize_command_name(str(cmd.get("command", "")))
            stderr = _normalize_signal(cmd.get("stderr", ""))
            stdout = _normalize_signal(cmd.get("stdout", ""))
            if exit_code not in (None, 0) and (stderr or stdout):
                if command_name in _LOW_VALUE_COMMANDS:
                    continue
                return stderr or stdout
            if exit_code not in (None, 0):
                if command_name in _LOW_VALUE_COMMANDS:
                    continue
                return f"command_exit:{command_name}:exit_{exit_code}"

    tool_fp = _tool_failure_fingerprint(snapshot)
    if tool_fp:
        return tool_fp

    validation_fp = _validation_failure_fingerprint(snapshot)
    if validation_fp:
        return validation_fp

    status = str(snapshot.get("status", "")).strip().lower()
    if status in {"failed", "error", "blocked", "cancelled", "timeout", "partial"}:
        return f"run_status:{status}"
    return None


def _severity_for_count(count: int) -> Literal["low", "medium", "high"]:
    if count >= 5:
        return "high"
    if count >= 2:
        return "medium"
    return "low"


def _suggest_prompt(fingerprint: str, sample_errors: list[str], domain: str) -> str:
    """Lemma-style heuristic: turn a recurring failure into a guard clause
    that can be appended to the agent's system / task prompt.

    This is intentionally deterministic + offline so it runs in CI.  An LLM
    upgrade can later replace the body of this function without changing the
    public contract.
    """
    fp = fingerprint.strip()
    sample = (sample_errors[0] if sample_errors else fp).strip()
    short = (sample[:160] + "…") if len(sample) > 160 else sample
    lower = fp.lower()

    # Pattern table — extend as we collect more recurring errors.
    if "timeout" in lower or "deadline" in lower:
        guidance = (
            "Operations in this domain have repeatedly timed out. Before "
            "calling long-running tools, set an explicit timeout AND have a "
            "fallback plan ready (chunk the work, cache prior results, or "
            "ask the user to confirm before retrying)."
        )
    elif "permission" in lower or "forbidden" in lower or "401" in lower or "403" in lower:
        guidance = (
            "Past runs failed with auth/permission errors. Verify "
            "credentials and scopes BEFORE attempting the protected "
            "operation; never retry blindly on 401/403."
        )
    elif "not found" in lower or "404" in lower or "missing" in lower:
        guidance = (
            "Past runs hit missing-resource errors. Confirm the resource "
            "exists (list/get) before referencing it, and surface a clear "
            "error to the user instead of silently continuing."
        )
    elif "conflict" in lower or "409" in lower or "duplicate" in lower:
        guidance = (
            "Past runs hit conflict / duplicate errors. Check for an "
            "existing record first; if found, decide upsert vs. abort with "
            "the user before mutating."
        )
    elif "validation" in lower or "schema" in lower or "invalid" in lower:
        guidance = (
            "Past runs failed schema/validation. Validate the payload "
            "against the API contract BEFORE the request and reject "
            "malformed input early with a precise error message."
        )
    elif "rate" in lower and "limit" in lower:
        guidance = (
            "Past runs were throttled. Add exponential backoff with jitter, "
            "and consolidate calls (batch where possible) instead of "
            "issuing them one-by-one."
        )
    else:
        guidance = (
            "This failure has recurred. Add a precondition check that "
            "detects the failing state before issuing the action, and a "
            "clear escalation path if the precondition is not met."
        )

    return (
        f"# Lessons-learned (auto-generated by atelier for domain '{domain}')\n"
        f"Recurring failure observed: {short}\n\n"
        f"Guidance: {guidance}\n"
        f"Verification: confirm the precondition above PASSES, then proceed."
    )


def analyze_failures(snapshots: list[dict[str, Any]]) -> list[FailureCluster]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for snap in snapshots:
        fp = _fingerprint(snap)
        if not fp:
            continue
        env_id = snap.get("environment_id") or "unknown"
        buckets[(env_id, fp)].append(snap)

    clusters: list[FailureCluster] = []
    for index, ((env_id, fp), snaps) in enumerate(sorted(buckets.items())):
        trace_ids = [s.get("session_id", "") for s in snaps if s.get("session_id")]
        sample_errors = [fp]
        suggested_block_title = f"Failure cluster: {fp[:80]}"
        suggested_rubric_check = f"observed_failure:{fp[:60]}"
        suggested_eval_case = f"replay_run:{trace_ids[0]}" if trace_ids else ""
        clusters.append(
            FailureCluster(
                id=f"cluster_{index:04d}",
                domain=env_id,
                fingerprint=fp,
                trace_ids=trace_ids,
                sample_errors=sample_errors,
                suggested_block_title=suggested_block_title,
                suggested_rubric_check=suggested_rubric_check,
                suggested_eval_case=suggested_eval_case,
                suggested_prompt=_suggest_prompt(fp, sample_errors, env_id),
                severity=_severity_for_count(len(trace_ids)),
            )
        )
    clusters.sort(key=lambda c: (-len(c.trace_ids), c.id))
    return clusters


class FailureAnalyzer:
    def __init__(
        self,
        runs_dir: Path | None = None,
        *,
        store: ContextStore | None = None,
        lesson_promoter: LessonPromoterCapability | None = None,
    ) -> None:
        self.runs_dir = Path(runs_dir) if runs_dir is not None else None
        self.store = store
        self.lesson_promoter = lesson_promoter or (LessonPromoterCapability(store) if store else None)

    def load_snapshots(self) -> list[dict[str, Any]]:
        if self.store is not None:
            traces = self.store.list_traces(status="failed", limit=500)
            return [t.model_dump(mode="json") for t in traces]

        if self.runs_dir is None:
            return []
        if not self.runs_dir.is_dir():
            return []
        snapshots: list[dict[str, Any]] = []
        for path in sorted(self.runs_dir.glob("*/run.json")):
            try:
                snapshots.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return snapshots

    def analyze(self) -> list[FailureCluster]:
        clusters = analyze_failures(self.load_snapshots())
        if self.store is not None and self.lesson_promoter is not None:
            for trace in self.store.list_traces(status="failed", limit=500):
                self.lesson_promoter.ingest_trace(trace)
        return clusters
