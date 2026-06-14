"""Scope-correct symbol rename — builds a batch of rich-edit descriptors.

Backends (by language, in fallback order):
  python    -> rope (pip install atelier[rename]) -> naive
  typescript/javascript -> ts-morph (node subprocess) -> naive
  rust      -> naive
  unknown   -> naive

The fallback ``naive`` backend rewrites only the exact lines the SCIP index
resolved to the symbol (its definition + each indexed reference), so it never
touches unrelated same-named identifiers on other lines. ast-grep is
deliberately NOT a rename backend: a bare-identifier pattern matches every node
of that name regardless of binding -- that is the ``codemod`` tool's job
(structural rewrites), not binding-aware symbol rename.

The returned list of dicts is passed directly to apply_rich_edits, which handles
atomic writes, rollback, and diff recording.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any

# -- backend detection --------------------------------------------------------

_LANGUAGE_BACKENDS: dict[str, list[str]] = {
    "python": ["rope", "naive"],
    "typescript": ["ts-morph", "naive"],
    "javascript": ["ts-morph", "naive"],
    "rust": ["naive"],
}


def _best_backend(language: str) -> str:
    for backend in _LANGUAGE_BACKENDS.get(language, ["naive"]):
        if backend == "rope":
            try:
                import rope  # noqa: F401

                return "rope"
            except ImportError:
                continue
        elif backend == "ts-morph":
            if shutil.which("node"):
                return "ts-morph"
        elif backend == "naive":
            return "naive"
    return "naive"


# -- naive rename -------------------------------------------------------------


def _naive_rename(
    symbol: dict[str, Any],
    usages: list[dict[str, Any]],
    new_name: str,
    old_name: str,
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Build rich-edit descriptors by rewriting only SCIP-resolved lines.

    The symbol index already pins the exact (file, line) of the definition and
    every reference of this binding, so ``old_name`` is rewritten only on those
    lines. Unrelated same-named identifiers on other lines are left untouched --
    unlike a whole-file or bare ast-grep pattern sweep, which over-renames. The
    one residual ambiguity is two distinct symbols sharing a name on a single
    line, which a line-level index cannot disambiguate.
    """
    pattern = re.compile(rf"\b{re.escape(old_name)}\b")
    # Each file -> the 1-based line numbers the index resolved to this symbol:
    # the definition line plus every indexed reference line.
    lines_by_file: dict[str, set[int]] = {}
    def_file = str(symbol.get("file_path") or "")
    def_line = int(symbol.get("start_line") or 0)
    if def_file and def_line:
        lines_by_file.setdefault(def_file, set()).add(def_line)
    for usage in usages:
        fp = str(usage.get("file_path") or "")
        line = int(usage.get("line") or 0)
        if fp and line:
            lines_by_file.setdefault(fp, set()).add(line)
    edits: list[dict[str, Any]] = []
    for fp, line_numbers in lines_by_file.items():
        try:
            content = (repo_root / fp).read_text(encoding="utf-8")
        except OSError:
            continue
        src_lines = content.splitlines(keepends=True)
        changed = False
        for line in line_numbers:
            if 1 <= line <= len(src_lines):
                rewritten = pattern.sub(new_name, src_lines[line - 1])
                if rewritten != src_lines[line - 1]:
                    src_lines[line - 1] = rewritten
                    changed = True
        if changed:
            edits.append({"file_path": fp, "overwrite": True, "new_string": "".join(src_lines)})
    return edits


# -- rope backend (Python only) -----------------------------------------------


def _rope_rename(
    symbol: dict[str, Any],
    new_name: str,
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Scope-correct rename using rope. Returns overwrite-style edits."""
    from rope.base import libutils
    from rope.base.project import Project
    from rope.refactor.rename import Rename

    project = Project(str(repo_root))
    try:
        abs_path = repo_root / symbol["file_path"]
        resource = libutils.path_to_resource(project, str(abs_path))
        # Convert byte offset -> character offset for files with multi-byte chars
        raw_bytes = abs_path.read_bytes()
        char_offset = len(raw_bytes[: symbol["start_byte"]].decode("utf-8", errors="replace"))
        renamer = Rename(project, resource, char_offset)
        changes = renamer.get_changes(new_name)
        edits: list[dict[str, Any]] = []
        for change in changes.changes:
            # rope ChangeContents has .resource.path and .new_contents
            if hasattr(change, "new_contents"):
                rel_path = str(Path(change.resource.path).relative_to(repo_root))
                edits.append(
                    {
                        "file_path": rel_path,
                        "overwrite": True,
                        "new_string": change.new_contents,
                    }
                )
        return edits
    finally:
        project.close()


# -- ts-morph backend (TypeScript/JavaScript) ---------------------------------

_TS_MORPH_SCRIPT = textwrap.dedent("""\
    const { Project } = require('ts-morph');
    const path = require('path');
    const fs = require('fs');

    const repoRoot = process.argv[2];
    const filePath = process.argv[3];
    const byteOffset = parseInt(process.argv[4], 10);
    const newName = process.argv[5];

    const project = new Project({ tsConfigFilePath: path.join(repoRoot, 'tsconfig.json'), skipLoadingLibFiles: false });
    const sourceFile = project.getSourceFileOrThrow(filePath);
    const absSource = fs.readFileSync(filePath, 'utf8');

    // Convert byte offset to character position
    const charOffset = Buffer.from(absSource).slice(0, byteOffset).toString('utf8').length;
    const node = sourceFile.getDescendantAtPos(charOffset);
    if (!node) { console.error('no node at offset'); process.exit(1); }

    node.rename(newName);

    const result = {};
    for (const sf of project.getSourceFiles()) {
        if (sf.wasForgotten()) continue;
        result[sf.getFilePath()] = sf.getFullText();
    }
    console.log(JSON.stringify(result));
""")


def _tsmorph_rename(
    symbol: dict[str, Any],
    new_name: str,
    repo_root: Path,
) -> list[dict[str, Any]]:
    with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
        f.write(_TS_MORPH_SCRIPT)
        script_path = f.name
    abs_file = str(repo_root / symbol["file_path"])
    try:
        proc = subprocess.run(
            ["node", script_path, str(repo_root), abs_file, str(symbol["start_byte"]), new_name],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(repo_root),
        )
    finally:
        Path(script_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ts-morph rename failed: {proc.stderr[:500]}")
    import json

    changed: dict[str, str] = json.loads(proc.stdout)
    edits: list[dict[str, Any]] = []
    for abs_path, content in changed.items():
        try:
            rel = str(Path(abs_path).relative_to(repo_root))
        except ValueError:
            continue
        edits.append({"file_path": rel, "overwrite": True, "new_string": content})
    return edits


# -- ast-grep backend ---------------------------------------------------------


# -- public API ---------------------------------------------------------------


def build_rename_edits(
    engine: Any,  # CodeContextEngine -- avoid circular import
    *,
    new_name: str,
    repo_root: Path,
    symbol_id: str | None = None,
    qualified_name: str | None = None,
    symbol_name: str | None = None,
    file_path: str | None = None,
    backend: str = "auto",
) -> list[dict[str, Any]]:
    """Resolve symbol, collect usages, return rich-edit descriptors for atomic rename.

    Raises:
        ValueError: if new_name is empty or symbol cannot be resolved.
        LookupError: if symbol not found.
    """
    if not new_name or not new_name.isidentifier():
        raise ValueError(f"new_name must be a valid identifier, got: {new_name!r}")

    symbol = engine.get_symbol(
        symbol_id=symbol_id,
        qualified_name=qualified_name,
        symbol_name=symbol_name,
        file_path=file_path,
    )
    old_name = str(symbol["symbol_name"])
    language = str(symbol.get("language") or "unknown").lower()

    # Collect all usages
    usages_payload = engine.find_references(
        symbol_id=str(symbol["symbol_id"]),
        qualified_name=str(symbol["qualified_name"]),
        symbol_name=old_name,
        file_path=str(symbol["file_path"]),
        snippet_lines=1,
        limit=500,
        budget_tokens=8000,
    )
    # Flatten usages from grouped or flat payload
    usages: list[dict[str, Any]] = []
    raw_refs = usages_payload.get("references") or usages_payload.get("usages") or []
    if isinstance(raw_refs, list):
        usages = [r for r in raw_refs if isinstance(r, dict)]
    elif isinstance(raw_refs, dict):
        for items in raw_refs.values():
            if isinstance(items, list):
                usages.extend(r for r in items if isinstance(r, dict))

    chosen = backend if backend != "auto" else _best_backend(language)

    if chosen == "rope" and language == "python":
        return _rope_rename(symbol, new_name, repo_root)

    if chosen == "ts-morph" and language in ("typescript", "javascript"):
        return _tsmorph_rename(symbol, new_name, repo_root)

    return _naive_rename(symbol, usages, new_name, old_name, repo_root)


__all__ = ["build_rename_edits"]
