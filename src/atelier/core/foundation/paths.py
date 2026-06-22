"""Path helpers for separating runtime state from Git-tracked lessons."""

from __future__ import annotations

import os
import re
from hashlib import sha256 as _sha256
from pathlib import Path

DEFAULT_STORE_DIRNAME = ".atelier"


def workspace_key(path: Path | str) -> str:
    """Human-readable workspace directory key.

    Strips the home-directory prefix and joins remaining path parts with ``-``.
    Characters outside ``[a-zA-Z0-9._-]`` are replaced with ``-``; consecutive
    dashes are collapsed.  Paths not under ``$HOME`` use the full absolute path
    (minus the leading ``/``).  Names longer than 120 chars are truncated and a
    6-char hash suffix is appended to avoid collisions.

    Examples::

        /home/alice/Projects/foo  →  Projects-foo
        /tmp/bench/bar            →  tmp-bench-bar
    """
    resolved = Path(path).expanduser().resolve()
    home = Path.home().resolve()
    try:
        rel = resolved.relative_to(home)
        parts = rel.parts
    except ValueError:
        parts = tuple(p for p in resolved.parts if p and p != "/")

    sanitized = [re.sub(r"[^a-zA-Z0-9.\-_]", "-", p) for p in parts if p]
    label = re.sub(r"-{2,}", "-", "-".join(sanitized)).strip("-")

    if len(label) > 120:
        digest = _sha256(str(resolved).encode()).hexdigest()[:6]
        label = label[:110].rstrip("-") + "--" + digest

    return label or _sha256(str(resolved).encode()).hexdigest()[:12]


DEFAULT_LESSONS_DIRNAME = ".atelier/lessons"


def default_store_root() -> Path:
    """Return the default runtime store root for traces and SQLite state."""
    configured = os.environ.get("ATELIER_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / DEFAULT_STORE_DIRNAME).resolve()


_HOST_WORKSPACE_ENV_VARS = (
    "ATELIER_WORKSPACE_ROOT",
    # Claude Code / Claude Desktop
    "CLAUDE_WORKSPACE_ROOT",
    # Cursor
    "CURSOR_WORKSPACE_ROOT",
    # VS Code / generic
    "VSCODE_CWD",
)


def resolve_workspace_root(root: Path | str | None = None) -> Path:
    """Resolve the active workspace root used for project-local lessons.

    Precedence:
    1. ``ATELIER_WORKSPACE_ROOT`` — explicit, authoritative
    2. Common host workspace env vars (``CLAUDE_WORKSPACE_ROOT``, etc.)
    3. Derive from the *root* path itself (e.g. parent of ``.atelier``)
    4. Current working directory — last resort
    """
    for env_var in _HOST_WORKSPACE_ENV_VARS:
        configured = os.environ.get(env_var, "").strip()
        if configured:
            return Path(configured).expanduser().resolve()

    derived = _derive_workspace_root(root)
    if derived is not None:
        return derived
    return Path.cwd().resolve()


def resolve_lessons_root(root: Path | str | None = None, lessons_root: Path | str | None = None) -> Path:
    """Resolve the Git-tracked lessons root.

    Precedence:
    1. Explicit constructor argument
    2. ATELIER_LESSONS_ROOT
    3. <workspace>/.atelier/lessons
    """
    if lessons_root is not None:
        return Path(lessons_root).expanduser().resolve()

    configured = os.environ.get("ATELIER_LESSONS_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    return (resolve_workspace_root(root) / DEFAULT_LESSONS_DIRNAME).resolve()


def resolve_session_state_path(workspace_root: Path | str | None = None) -> Path:
    """Resolve the path for session-specific state (failures, current run ID).

    Stored within the global store root under a workspace-specific subfolder
    to prevent collisions between multiple open projects.
    """
    root = default_store_root()
    ws = resolve_workspace_root(Path(workspace_root) if workspace_root else None)
    h = workspace_key(ws)
    return root / "workspaces" / h / "session_state.json"


def _derive_workspace_root(root: Path | str | None) -> Path | None:
    if root is None:
        return None

    candidate = Path(root).expanduser().resolve()
    default_home_store = (Path.home() / DEFAULT_STORE_DIRNAME).resolve()
    if candidate == default_home_store:
        return None

    # Do not treat the workspace hash subfolder as a project root
    if "workspaces" in candidate.parts:
        return None

    # .atelier/lessons is two levels deep — peel both parts to reach workspace
    if candidate.name == "lessons" and candidate.parent.name == DEFAULT_STORE_DIRNAME:
        return candidate.parent.parent
    if candidate.name == DEFAULT_STORE_DIRNAME:
        return candidate.parent
    if candidate.parent != candidate:
        return candidate.parent
    return candidate


def confine_to_root(candidate: str | Path, root: str | Path) -> Path:
    """Resolve *candidate* and ensure it stays within *root*.

    Both paths are ``expanduser()``-ed and ``resolve()``-d, which means symlinks
    are followed; a symlink that points outside *root* therefore resolves to an
    out-of-root target and is rejected. The resolved candidate is returned only
    when it is *root* itself or lives beneath it.

    Raises:
        ValueError: if the resolved candidate escapes *root*.
    """
    resolved_root = Path(root).expanduser().resolve()
    resolved_candidate = Path(candidate).expanduser().resolve()
    if resolved_candidate != resolved_root and not resolved_candidate.is_relative_to(resolved_root):
        raise ValueError("path escapes the allowed root")
    return resolved_candidate


def ensure_gitignore(project_root: Path) -> list[str]:
    """Create/update ``.atelier/.gitignore`` to ignore everything inside ``.atelier/``.

    Keeps the ``.atelier/`` directory visible in git for brand awareness while
    preventing cache files, binaries, and other project-local runtime data from
    being committed.  Idempotent: returns a non-empty list on first run (entries
    added) and an empty list on subsequent runs (already correct).
    """
    atelier_dir = project_root / ".atelier"
    atelier_dir.mkdir(parents=True, exist_ok=True)
    gitignore_path = atelier_dir / ".gitignore"
    content = "# Atelier runtime data \u2014 keep the directory, ignore its contents\n*\n"
    if gitignore_path.exists() and gitignore_path.read_text("utf-8") == content:
        return []
    gitignore_path.write_text(content, encoding="utf-8")
    return ["*"]


_ensure_gitignore = ensure_gitignore  # compat alias for internal use


def resolve_workspace_store_dir(root: Path | str | None = None, workspace_root: Path | str | None = None) -> Path:
    """Return the per-project runtime subdir under the global store root.

    Mirrors the convention already used by ``code_context.sqlite`` and
    ``session_state.json``: ``<store_root>/workspaces/<sha256(workspace)[:12]>``.
    Keeps per-project runtime artifacts (blocks/rubrics mirrors, etc.) isolated so
    one project cannot pollute another, while living in the global store rather
    than the Git-tracked ``.atelier/lessons`` (which is reserved for real knowledge).
    """
    store_root = Path(root).expanduser().resolve() if root is not None else default_store_root()
    ws = resolve_workspace_root(workspace_root if workspace_root is not None else root)
    digest = workspace_key(ws)
    return store_root / "workspaces" / digest


def resolve_store_root_for_workspace(workspace_root: Path | str | None = None) -> Path:
    """Return the per-workspace store root, falling back to the global store.

    When a workspace root is known this returns
    ``<store_root>/workspaces/<workspace_key>/`` so that sessions and raw
    artifacts live alongside the code index for the same project.  When the
    workspace root cannot be determined the global store root is returned so
    callers never crash.

    Precedence for workspace discovery (when *workspace_root* is not given):
    1. ``ATELIER_WORKSPACE_ROOT``
    2. Common host env vars (``CLAUDE_WORKSPACE_ROOT``, etc.)
    3. Current working directory — last resort
    """
    if workspace_root is None:
        for env_var in _HOST_WORKSPACE_ENV_VARS:
            configured = os.environ.get(env_var, "").strip()
            if configured:
                workspace_root = Path(configured)
                break
        else:
            cwd = Path.cwd()
            home = Path.home()
            # Only use cwd when it's clearly a project dir (not home itself or
            # a system dir), to avoid mixing personal-root sessions.
            if cwd != home and not str(cwd).startswith(str(home / ".")) and cwd != Path("/"):
                workspace_root = cwd

    if workspace_root is not None:
        return resolve_workspace_store_dir(workspace_root=workspace_root)
    return default_store_root()


__all__ = [
    "DEFAULT_LESSONS_DIRNAME",
    "DEFAULT_STORE_DIRNAME",
    "confine_to_root",
    "default_store_root",
    "resolve_lessons_root",
    "resolve_session_state_path",
    "resolve_store_root_for_workspace",
    "resolve_workspace_root",
    "resolve_workspace_store_dir",
    "workspace_key",
]
