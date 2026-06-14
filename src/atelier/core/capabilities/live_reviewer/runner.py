"""Run a code review out-of-band via owned execution and parse the verdict."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from atelier.core.capabilities.live_reviewer.knowledge import collect_review_context
from atelier.core.capabilities.live_reviewer.settings import (
    ReviewerSettings,
    split_provider_model,
)
from atelier.core.capabilities.owned_execution_lanes import execute_owned_prompt
from atelier.core.capabilities.owned_execution_routing import (
    OwnedRouteRequest,
    select_owned_route,
)

_VERDICT_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)

_REVIEW_CONTRACT = (
    "You are an adversarial code reviewer. Find what is wrong; do not validate "
    "that work was done. Apply the verification ladder (existence -> substantive "
    "-> wired -> data flow). Every finding needs a severity (Blocker or Warning), "
    "a file:symbol:line anchor, and a concrete fix. Default to NEEDS_FIX: a DONE "
    "verdict requires positive proof every change is correct.\n\n"
    "Review ONLY the diff(s) below. End your output with exactly one fenced JSON "
    "block and nothing after it:\n"
    '```json\n{"verdict": "DONE" | "NEEDS_FIX", "checklist": "<one line>", '
    '"missing": "<bulleted gaps, empty when DONE>"}\n```\n'
)


def _git_diff(path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def _build_prompt(diffs: Mapping[str, str], kb: str = "") -> str:
    parts = [_REVIEW_CONTRACT]
    if kb:
        parts.append(kb)
    parts.append("## Diffs under review\n")
    for path, diff in diffs.items():
        parts.append(f"### {path}\n```diff\n{diff}\n```\n")
    return "\n".join(parts)


def parse_verdict(text: str) -> dict[str, Any]:
    """Extract the final fenced JSON verdict. Safe default, never raises."""
    for block in reversed(_VERDICT_RE.findall(text or "")):
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "verdict" in obj:
            verdict = str(obj.get("verdict") or "").strip().upper()
            return {
                "verdict": "DONE" if verdict == "DONE" else "NEEDS_FIX",
                "checklist": str(obj.get("checklist") or ""),
                "missing": str(obj.get("missing") or ""),
            }
    return {"verdict": "ERROR", "checklist": "", "missing": "review output could not be parsed"}


def run_review(
    session_id: str,
    mode: str,
    paths: Sequence[str],
    settings: ReviewerSettings,
    root: str | Path,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Review the working-tree diff of ``paths`` and return a verdict record."""
    diffs = {path: _git_diff(path) for path in paths if path}
    diffs = {path: diff for path, diff in diffs.items() if diff}
    base: dict[str, Any] = {"mode": mode, "paths": list(diffs.keys()), "session_id": session_id}
    if not diffs:
        return {**base, "verdict": "DONE", "checklist": "no diff to review", "missing": ""}

    repo_root = os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd()
    prompt = _build_prompt(diffs, collect_review_context(root, repo_root))
    provider, model_id = split_provider_model(settings.model_for(mode))
    if provider and model_id:
        request = OwnedRouteRequest(
            tool_name="agent",
            task_text=prompt,
            mode="explicit",
            provider=provider,
            model=model_id,
            host_agent="atelier:review",
        )
        allow_fallback = False
    else:
        request = OwnedRouteRequest(
            tool_name="agent",
            task_text=prompt,
            mode="auto",
            budget="best" if mode == "deep" else "cheap",
            model=model_id,
            host_agent="atelier:review",
        )
        allow_fallback = True

    decision = select_owned_route(root, request, env=env)
    result = execute_owned_prompt(
        prompt,
        root=root,
        tool_name="agent",
        task_text=prompt,
        decision=decision,
        host_agent="atelier:review",
        allow_fallback=allow_fallback,
    )
    return {**base, **parse_verdict(result.output)}
