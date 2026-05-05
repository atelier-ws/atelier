"""Static starter ReasonBlock pack support."""

from __future__ import annotations

import shutil
import tomllib
from contextlib import suppress
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from atelier.core.foundation.models import ReasonBlock


@dataclass(frozen=True)
class StackBlockEntry:
    file: str
    title: str
    summary: str


@dataclass(frozen=True)
class StackManifest:
    slug: str
    name: str
    description: str
    version: str
    blocks: list[StackBlockEntry]
    root: Path


def list_stacks() -> list[StackManifest]:
    stacks: dict[str, StackManifest] = {}
    for root in _template_roots():
        if not root.exists():
            continue
        for child in sorted(path for path in root.iterdir() if path.is_dir()):
            if child.name in stacks:
                continue
            manifest_path = child / "manifest.toml"
            if not manifest_path.exists():
                continue
            stacks[child.name] = _load_manifest(child.name, child)
    return [stacks[key] for key in sorted(stacks)]


def get_stack(slug: str) -> StackManifest:
    for manifest in list_stacks():
        if manifest.slug == slug:
            return manifest
    available = ", ".join(item.slug for item in list_stacks()) or "none"
    raise ValueError(f"unknown stack {slug!r}; available stacks: {available}")


def copy_stack_templates(stack: str, blocks_dir: Path) -> tuple[int, int]:
    manifest = get_stack(stack)
    blocks_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    for entry in manifest.blocks:
        source = manifest.root / entry.file
        if not source.exists():
            raise ValueError(f"stack {stack!r} references missing block template: {entry.file}")
        load_template_block(source)
        target = blocks_dir / f"template_{source.name}"
        if target.exists():
            skipped += 1
            continue
        shutil.copyfile(source, target)
        copied += 1
    return copied, skipped


def load_template_block(path: Path) -> ReasonBlock:
    raw = path.read_text(encoding="utf-8")
    data = _frontmatter(raw)
    return ReasonBlock.model_validate(data)


def _load_manifest(slug: str, root: Path) -> StackManifest:
    data = tomllib.loads((root / "manifest.toml").read_text(encoding="utf-8"))
    blocks = [StackBlockEntry(**item) for item in data.get("blocks", [])]
    return StackManifest(
        slug=slug,
        name=str(data["name"]),
        description=str(data["description"]),
        version=str(data["version"]),
        blocks=blocks,
        root=root,
    )


def _frontmatter(raw: str) -> dict[str, Any]:
    if not raw.startswith("---\n"):
        raise ValueError("template ReasonBlock must start with YAML frontmatter")
    try:
        _, frontmatter, _body = raw.split("---\n", 2)
    except ValueError as exc:
        raise ValueError("template ReasonBlock frontmatter is not closed") from exc
    data = yaml.safe_load(frontmatter)
    if not isinstance(data, dict):
        raise ValueError("template ReasonBlock frontmatter must be a mapping")
    return data


def _template_roots() -> list[Path]:
    roots: list[Path] = []
    cwd_root = Path.cwd() / "templates" / "reasonblocks"
    source_root = Path(__file__).resolve().parents[4] / "templates" / "reasonblocks"
    roots.extend([cwd_root, source_root])
    with (
        suppress(FileNotFoundError, ModuleNotFoundError),
        resources.as_file(
            resources.files("atelier") / "templates" / "reasonblocks"
        ) as package_root,
    ):
        roots.append(package_root)
    return list(dict.fromkeys(roots))


__all__ = [
    "StackBlockEntry",
    "StackManifest",
    "copy_stack_templates",
    "get_stack",
    "list_stacks",
    "load_template_block",
]
