"""Knowledge that feeds the live reviewer.

Two layers, mirroring a code-review knowledge base:

- **repo lessons** — the first heading of each ``.lessons/blocks/*.md`` (the
  conventions Atelier has learned in this repo).
- **personal overlay** — ``review_overlay.json`` under the Atelier root, which the
  user curates: ``notes`` (rules to apply), ``boost`` (weight up), ``suppress``
  (finding classes the team has chosen not to flag).

All reads are fail-open: any problem yields an empty context so a review still
runs.
"""

from __future__ import annotations

import json
from pathlib import Path

_MAX_LESSONS = 8
_MAX_ITEMS = 12


def overlay_path(root: str | Path) -> Path:
    return Path(root) / "review_overlay.json"


def load_overlay(root: str | Path) -> dict[str, list[str]]:
    """Read the personal review overlay; always returns the three keys."""
    try:
        data = json.loads(overlay_path(root).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"notes": [], "suppress": [], "boost": []}
    if not isinstance(data, dict):
        return {"notes": [], "suppress": [], "boost": []}

    def _strs(key: str) -> list[str]:
        value = data.get(key)
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:_MAX_ITEMS]

    return {"notes": _strs("notes"), "suppress": _strs("suppress"), "boost": _strs("boost")}


def _repo_lessons(repo_root: str | Path) -> list[str]:
    blocks = Path(repo_root) / ".lessons" / "blocks"
    if not blocks.is_dir():
        return []
    try:
        files = sorted(blocks.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    out: list[str] = []
    for path in files[:_MAX_LESSONS]:
        try:
            text = path.read_text("utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                out.append(stripped)
                break
    return out


def collect_review_context(root: str | Path, repo_root: str | Path) -> str:
    """Build the reviewer's knowledge block (empty string when there's nothing)."""
    overlay = load_overlay(root)
    lessons = _repo_lessons(repo_root)
    notes, suppress, boost = overlay["notes"], overlay["suppress"], overlay["boost"]
    if not (notes or suppress or boost or lessons):
        return ""
    lines = ["## Repository review knowledge — apply these"]
    lines.extend(f"- rule: {note}" for note in notes)
    lines.extend(f"- repo lesson: {lesson}" for lesson in lessons)
    if boost:
        lines.append("Weight these areas more heavily: " + ", ".join(boost))
    if suppress:
        lines.append("Do NOT raise findings about (suppressed by the team): " + ", ".join(suppress))
    return "\n".join(lines) + "\n"
