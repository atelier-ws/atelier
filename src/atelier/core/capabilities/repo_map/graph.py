"""Reference graph construction for repo maps."""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from atelier.infra.tree_sitter.tags import Tag, detect_language, extract_tags

_SKIP_PARTS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv"}


def iter_source_files(repo_root: Path, include_globs: list[str] | None = None) -> list[Path]:
    patterns = include_globs or [
        "**/*.py",
        "**/*.js",
        "**/*.jsx",
        "**/*.ts",
        "**/*.tsx",
        "**/*.go",
        "**/*.rs",
    ]
    files: list[Path] = []
    for pattern in patterns:
        for path in repo_root.glob(pattern):
            if not path.is_file():
                continue
            if any(part in _SKIP_PARTS for part in path.parts):
                continue
            if detect_language(path) is None:
                continue
            files.append(path)
    return sorted(set(files))


def build_reference_graph(
    repo_root: str | Path, files: list[str] | None = None
) -> tuple[nx.DiGraph, dict[str, list[Tag]]]:
    """Build a file graph from symbol references to definitions."""
    root = Path(repo_root)
    paths = [root / file for file in files] if files else iter_source_files(root)
    tags_by_file: dict[str, list[Tag]] = {}
    definitions: dict[str, set[str]] = {}
    for path in paths:
        try:
            tags = extract_tags(path)
        except OSError:
            tags = []
        rel = str(path.relative_to(root)) if path.is_absolute() or path.exists() else str(path)
        tags_by_file[rel] = tags
        for tag in tags:
            if tag.kind == "definition":
                definitions.setdefault(tag.name, set()).add(rel)

    graph = nx.DiGraph()
    for rel in tags_by_file:
        graph.add_node(rel)
    for rel, tags in tags_by_file.items():
        for tag in tags:
            if tag.kind != "reference":
                continue
            for def_file in definitions.get(tag.name, set()):
                if def_file == rel:
                    continue
                weight = float(graph.get_edge_data(rel, def_file, {}).get("weight", 0.0)) + 1.0
                graph.add_edge(rel, def_file, weight=weight)
    return graph, tags_by_file


__all__ = ["build_reference_graph", "iter_source_files"]
