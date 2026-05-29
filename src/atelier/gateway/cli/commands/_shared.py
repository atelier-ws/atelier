"""Shared CLI-only glue used across multiple Atelier command modules.

These helpers are moved verbatim from ``app.py``. They are *CLI-only* plumbing
(output emission, store/runtime construction, memory input handling, tag
parsing) -- NOT business logic (CLAUDE.md:55). Command modules import them from
here; ``app.py`` re-imports them so every existing call site is unchanged.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import click

_REDACTION_PLACEHOLDER_RE = re.compile(r"<redacted[^>]*>")


def _load_store(root: Path) -> Any:
    from atelier.infra.storage.factory import create_store

    try:
        store = create_store(root)
    except (RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    db_path = getattr(store, "db_path", None)
    if db_path is not None and not Path(db_path).exists():
        raise click.ClickException(f"No atelier store at {root}. Run `atelier init` first.")
    return store


def _core_runtime(root: Path) -> Any:
    from atelier.core.runtime import AtelierRuntimeCore

    return AtelierRuntimeCore(root)


def _emit(data: Any, *, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        click.echo(data)


def _redact_memory_input(text: str, field_name: str) -> str:
    from atelier.core.foundation.redaction import redact

    redacted = redact(text)
    if not text:
        return redacted
    remaining = _REDACTION_PLACEHOLDER_RE.sub("", redacted)
    if len(remaining.strip()) < len(text.strip()) * 0.5:
        raise click.ClickException(f"{field_name} rejected: likely secret leakage")
    return redacted


def _read_memory_value(value: str) -> str:
    if not value.startswith("@"):
        return value
    path_text = value[1:]
    if path_text == "/dev/stdin" or path_text == "-":
        return sys.stdin.read()
    return Path(path_text).read_text(encoding="utf-8")


def _parse_tags(values: tuple[str, ...]) -> list[str]:
    tags: list[str] = []
    for value in values:
        tags.extend(tag.strip() for tag in value.split(",") if tag.strip())
    return tags


def _smart_state_path(root: Path) -> Path:
    return Path(root) / "smart_state.json"


def _load_smart_state(root: Path) -> dict[str, Any]:
    p = _smart_state_path(root)
    if not p.exists():
        return {"mode": "shadow", "cache": {}, "savings": {"calls_avoided": 0, "tokens_saved": 0}}
    data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return data


def _save_smart_state(root: Path, state: dict[str, Any]) -> None:
    p = _smart_state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")
