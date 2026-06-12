"""``atelier project`` — project intelligence snapshot.

Scans the current working directory and renders a rich breakdown:
  - language distribution (files + LOC)
  - top files by size / LOC
  - top directories by LOC
  - code-to-test ratio, doc coverage
  - Atelier projection savings estimate (tokens saved if read tool runs on all source)

Run:
    atelier project [PATH]
    atelier project --json
    atelier project --top 10
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click

# ---------------------------------------------------------------------------
# Language registry
# ---------------------------------------------------------------------------


@dataclass
class LangDef:
    name: str
    exts: tuple[str, ...]
    comment: str = "#"
    color: str = "cyan"


_LANGS: list[LangDef] = [
    LangDef("Python", (".py",), "#", "bright_yellow"),
    LangDef("TypeScript", (".ts", ".tsx"), "//", "bright_cyan"),
    LangDef("JavaScript", (".js", ".jsx", ".mjs"), "//", "yellow"),
    LangDef("Rust", (".rs",), "//", "red"),
    LangDef("Go", (".go",), "//", "cyan"),
    LangDef("Swift", (".swift",), "//", "orange3"),
    LangDef("Kotlin", (".kt", ".kts"), "//", "bright_magenta"),
    LangDef("Java", (".java",), "//", "bright_blue"),
    LangDef("C/C++", (".c", ".cpp", ".cc", ".h", ".hpp"), "//", "blue"),
    LangDef("C#", (".cs",), "//", "bright_green"),
    LangDef("Ruby", (".rb",), "#", "red"),
    LangDef("PHP", (".php",), "//", "magenta"),
    LangDef("Scala", (".scala",), "//", "bright_red"),
    LangDef("Shell", (".sh", ".bash", ".zsh"), "#", "green"),
    LangDef("HTML", (".html", ".htm"), "<!--", "orange1"),
    LangDef("CSS", (".css", ".scss", ".sass"), "/*", "bright_blue"),
    LangDef("TOML", (".toml",), "#", "dim white"),
    LangDef("YAML", (".yaml", ".yml"), "#", "dim white"),
    LangDef("JSON", (".json",), "", "dim white"),
    LangDef("Markdown", (".md", ".mdx"), "", "dim white"),
    LangDef("Astro", (".astro",), "//", "bright_cyan"),
]

_EXT_TO_LANG: dict[str, LangDef] = {}
for _ld in _LANGS:
    for _ext in _ld.exts:
        _EXT_TO_LANG[_ext] = _ld

# Files/dirs to always skip
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "target",
        "vendor",
        ".cargo",
        "coverage",
        ".coverage",
        "htmlcov",
        ".tox",
        "eggs",
        ".eggs",
        "buck-out",
        "_build",
    }
)


# ---------------------------------------------------------------------------
# File stats
# ---------------------------------------------------------------------------


@dataclass
class FileStats:
    path: Path
    rel: str
    lang: LangDef | None
    size_bytes: int
    lines: int
    code_lines: int  # non-blank, non-comment
    comment_lines: int
    blank_lines: int
    is_test: bool
    is_doc: bool

    @property
    def ext(self) -> str:
        return self.path.suffix.lower()

    @property
    def tokens(self) -> int:
        return _est_tokens(self.size_bytes)

    @property
    def proj_tokens(self) -> int:
        """Tokens after projection; same as raw if not projectable."""
        if _proj_reason(self) is not None:
            return self.tokens
        return int(self.tokens * (1 - _proj_save_rate(self.lines)))


def _count_lines(text: str, comment_prefix: str) -> tuple[int, int, int]:
    """Returns (code, comment, blank)."""
    code = comment = blank = 0
    cp = comment_prefix.strip()
    for line in text.splitlines():
        s = line.strip()
        if not s:
            blank += 1
        elif cp and s.startswith(cp):
            comment += 1
        else:
            code += 1
    return code, comment, blank


def _scan_file(path: Path, root: Path) -> FileStats | None:
    ext = path.suffix.lower()
    lang = _EXT_TO_LANG.get(ext)
    if lang is None:
        return None  # skip files with unrecognized extensions
    try:
        size = path.stat().st_size
        if size > 2 * 1024 * 1024:  # skip files > 2MB
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return None

    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    cp = lang.comment if lang else "#"
    code, comment, blank = _count_lines(text, cp)

    name = path.name.lower()
    rel = str(path.relative_to(root))
    is_test = bool(
        re.search(r"(^|/)tests?/", rel)
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".spec.ts")
        or name.endswith(".test.tsx")
        or name.endswith(".spec.tsx")
    )
    is_doc = ext in (".md", ".mdx", ".rst", ".txt") or "docs/" in rel or "doc/" in rel

    return FileStats(
        path=path,
        rel=rel,
        lang=lang,
        size_bytes=size,
        lines=lines,
        code_lines=code,
        comment_lines=comment,
        blank_lines=blank,
        is_test=is_test,
        is_doc=is_doc,
    )


# ---------------------------------------------------------------------------
# Projection savings estimate
# tiktoken costs ~100ms to import, so we lazily estimate without it:
# Average English/code token ≈ 4 chars. Projection outline typically saves ~60%
# on large files (>200 LOC). We use a conservative 50%.
# ---------------------------------------------------------------------------

_OUTLINE_THRESHOLD_LOC = 200  # matches SemanticFileMemoryCapability.smart_read default
_PROJ_SAVE_OUTLINE = 0.55  # outline mode: structure only, bodies omitted
_PROJ_SAVE_COMPACT = 0.10  # compact mode: whitespace normalization only

# No code structure → outline can't extract signatures; only whitespace compact applies
_NON_PROJ_TYPES = frozenset({"JSON", "YAML", "TOML", "Markdown", "HTML", "CSS"})


def _proj_reason(f: FileStats) -> str | None:
    """None = outline-eligible (best savings). String = why outline doesn't apply."""
    if f.lang is None:
        return "unrecognized type"
    if f.lang.name in _NON_PROJ_TYPES:
        return "no code structure (compact only)"
    if f.lines < _OUTLINE_THRESHOLD_LOC:
        return f"< {_OUTLINE_THRESHOLD_LOC} LOC (compact only)"
    return None


def _proj_save_rate(lines: int) -> float:
    """Outline for large code files; compact whitespace normalization for small ones."""
    return _PROJ_SAVE_OUTLINE if lines >= _OUTLINE_THRESHOLD_LOC else _PROJ_SAVE_COMPACT


def _est_tokens(chars: int) -> int:
    return max(1, chars // 4)


@dataclass
class ProjectSnapshot:
    root: Path
    files: list[FileStats] = field(default_factory=list)

    # aggregated
    by_lang: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(
            lambda: {"files": 0, "loc": 0, "code": 0, "bytes": 0, "tokens": 0, "proj_tokens": 0}
        )
    )
    by_dir: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: {"files": 0, "loc": 0}))

    total_files: int = 0
    total_loc: int = 0
    total_code: int = 0
    total_bytes: int = 0
    test_files: int = 0
    doc_files: int = 0
    source_files: int = 0

    large_files: int = 0  # projectable files (known code lang, not data/markup)
    proj_tokens_saved: int = 0  # estimated tokens saved by projection on large files
    proj_tokens_total: int = 0  # total tokens if read raw
    proj_tokens_after: int = 0  # total tokens after projection

    todos: int = 0
    fixmes: int = 0

    def build(self) -> None:
        for f in self.files:
            lang_name = f.lang.name if f.lang else "Other"
            self.by_lang[lang_name]["files"] += 1
            self.by_lang[lang_name]["loc"] += f.lines
            self.by_lang[lang_name]["code"] += f.code_lines
            self.by_lang[lang_name]["bytes"] += f.size_bytes
            self.by_lang[lang_name]["tokens"] += f.tokens
            self.by_lang[lang_name]["proj_tokens"] += f.proj_tokens

            top_dir = f.rel.split("/")[0] if "/" in f.rel else "."
            self.by_dir[top_dir]["files"] += 1
            self.by_dir[top_dir]["loc"] += f.lines

            self.total_files += 1
            self.total_loc += f.lines
            self.total_code += f.code_lines
            self.total_bytes += f.size_bytes
            if f.is_test:
                self.test_files += 1
            elif f.is_doc:
                self.doc_files += 1
            else:
                self.source_files += 1

            raw = f.tokens
            self.proj_tokens_total += raw
            self.proj_tokens_after += f.proj_tokens
            if _proj_reason(f) is None:
                self.large_files += 1
                self.proj_tokens_saved += raw - f.proj_tokens

    def to_json(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "total_files": self.total_files,
            "total_loc": self.total_loc,
            "total_code_lines": self.total_code,
            "total_bytes": self.total_bytes,
            "test_files": self.test_files,
            "doc_files": self.doc_files,
            "source_files": self.source_files,
            "large_files_above_projection_threshold": self.large_files,
            "projection_tokens_saved_estimate": self.proj_tokens_saved,
            "projection_tokens_total_estimate": self.proj_tokens_total,
            "projection_tokens_after_estimate": self.proj_tokens_after,
            "by_lang": dict(self.by_lang),
            "by_dir": dict(self.by_dir),
            "top_files_by_loc": [
                {"path": f.rel, "loc": f.lines, "code": f.code_lines, "lang": f.lang.name if f.lang else "?"}
                for f in sorted(self.files, key=lambda x: x.lines, reverse=True)[:10]
            ],
        }


def _load_gitignore_patterns(root: Path) -> list[tuple[Path, str]]:
    """Walk the tree and collect (gitignore_dir, pattern) pairs from every .gitignore found."""
    import fnmatch as _fnmatch  # noqa: F401 — used in _is_gitignored

    pairs: list[tuple[Path, str]] = []
    for gi in root.rglob(".gitignore"):
        gi_dir = gi.parent
        try:
            for raw in gi.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith("!"):
                    continue  # skip blanks, comments, negations (rarely used, keep safe)
                pairs.append((gi_dir, line))
        except OSError:
            pass
    return pairs


def _is_gitignored(path: Path, root: Path, patterns: list[tuple[Path, str]]) -> bool:
    """Return True if *path* matches any collected gitignore pattern."""
    import fnmatch

    rel = path.relative_to(root)
    rel_str = rel.as_posix()
    parts = rel.parts

    for gi_dir, pat in patterns:
        # Compute path relative to the gitignore's directory
        try:
            local_rel = path.relative_to(gi_dir).as_posix()
        except ValueError:
            continue  # file not under this gitignore's directory

        p = pat.rstrip("/")

        # Anchored pattern (contains "/" not at end): match from gitignore dir
        if "/" in p:
            if fnmatch.fnmatch(local_rel, p) or fnmatch.fnmatch(local_rel, p.lstrip("/")):
                return True
            # ** anywhere-depth shorthand
            if p.startswith("**/"):
                tail = p[3:]
                if any(fnmatch.fnmatch("/".join(parts[i:]), tail) for i in range(len(parts))):
                    return True
        else:
            # Unanchored: match against any individual path component (dir or filename)
            for part in parts:
                if fnmatch.fnmatch(part, p):
                    return True
            # Also match against the full relative string for patterns like *.lock
            if fnmatch.fnmatch(rel_str, p):
                return True

    return False


def _get_files(root: Path) -> list[Path]:
    """Return file list: git ls-files if in a git repo, else rglob respecting .gitignore."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            paths = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                p = root / line
                if p.is_file():
                    paths.append(p)
            return paths
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fallback: rglob + manual _SKIP_DIRS + .gitignore parsing
    gitignore_patterns = _load_gitignore_patterns(root)

    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.relative_to(root).parts)
        if parts & _SKIP_DIRS:
            continue
        if path.name.startswith("."):
            continue
        if gitignore_patterns and _is_gitignored(path, root, gitignore_patterns):
            continue
        files.append(path)
    return files


def _scan(root: Path, respect_gitignore: bool = True) -> ProjectSnapshot:
    snap = ProjectSnapshot(root=root)
    for path in _get_files(root):
        if not path.is_file():
            continue
        parts = set(path.relative_to(root).parts)
        if parts & _SKIP_DIRS:
            continue
        if path.name.startswith("."):
            continue
        fs = _scan_file(path, root)
        if fs is not None:
            snap.files.append(fs)
    snap.build()
    return snap


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n //= 1024
    return f"{n:.0f} TB"


def _fmt_num(n: int) -> str:
    return f"{n:,}"


def _bar(fraction: float, width: int = 20) -> str:
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


def _render(snap: ProjectSnapshot, top_n: int) -> None:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    proj_name = snap.root.name
    save_pct = int(snap.proj_tokens_saved / max(1, snap.proj_tokens_total) * 100)
    code_ratio = int(snap.source_files / max(1, snap.total_files) * 100)
    test_ratio = (
        int(snap.test_files / max(1, snap.source_files + snap.test_files) * 100)
        if (snap.source_files + snap.test_files)
        else 0
    )

    # ── Header ──
    console.print()
    console.rule(f"[bold bright_white]> {proj_name}[/]  [dim]{snap.root}[/]")
    console.print()

    # ── Hero metrics ──
    hero = Table.grid(expand=True)
    for _ in range(7):
        hero.add_column(justify="center")

    def _chip(label: str, value: str, color: str) -> Panel:
        return Panel(
            f"[bold {color}]{value}[/]\n[dim]{label}[/]",
            border_style="dim",
            padding=(0, 2),
        )

    total_k = snap.proj_tokens_total // 1000
    after_k = snap.proj_tokens_after // 1000
    hero.add_row(
        _chip("Files", _fmt_num(snap.total_files), "bright_white"),
        _chip("Lines of Code", _fmt_num(snap.total_loc), "bright_cyan"),
        _chip("Code Lines", _fmt_num(snap.total_code), "bright_yellow"),
        _chip("Size", _fmt_bytes(snap.total_bytes), "white"),
        _chip("Languages", str(len(snap.by_lang)), "bright_magenta"),
        _chip("Raw Tokens", f"{_fmt_num(total_k)}k", "dim white"),
        _chip("Projected", f"{_fmt_num(after_k)}k", "bright_green"),
    )
    console.print(hero)
    console.print()

    # ── Language breakdown ──
    console.print("[bold bright_white]  Languages[/]  [dim]by lines of code[/]")
    console.print()

    lang_table = Table(box=box.SIMPLE, show_header=True, header_style="dim", padding=(0, 1))
    lang_table.add_column("Language", style="bold", min_width=14)
    lang_table.add_column("Files", justify="right", style="dim white")
    lang_table.add_column("LOC", justify="right")
    lang_table.add_column("Raw tok", justify="right")
    lang_table.add_column("Proj tok", justify="right")
    lang_table.add_column("Share", min_width=20)
    lang_table.add_column("%", justify="right")

    sorted_langs = sorted(snap.by_lang.items(), key=lambda x: x[1]["loc"], reverse=True)
    max_loc = sorted_langs[0][1]["loc"] if sorted_langs else 1

    for lang_name, stats in sorted_langs[:top_n]:
        ld_match = next((ld for ld in _LANGS if ld.name == lang_name), None)
        color = ld_match.color if ld_match else "white"
        frac = stats["loc"] / max_loc
        pct = stats["loc"] / max(1, snap.total_loc) * 100
        raw_k = stats["tokens"] // 1000
        proj_k = stats["proj_tokens"] // 1000
        proj_str = f"[bright_green]{_fmt_num(proj_k)}k[/]" if proj_k < raw_k else f"[dim]{_fmt_num(proj_k)}k[/]"
        lang_table.add_row(
            f"[{color}]{lang_name}[/]",
            _fmt_num(stats["files"]),
            _fmt_num(stats["loc"]),
            f"[dim]{_fmt_num(raw_k)}k[/]",
            proj_str,
            f"[{color}]{_bar(frac, 20)}[/]",
            f"[dim]{pct:.1f}%[/]",
        )

    console.print(lang_table)

    # ── Top files ──
    console.print("[bold bright_white]  Top Files[/]  [dim]by lines of code[/]")
    console.print()

    file_table = Table(box=box.SIMPLE, show_header=True, header_style="dim", padding=(0, 1))
    file_table.add_column("#", justify="right", style="dim", width=3)
    file_table.add_column("File", no_wrap=False, min_width=38)
    file_table.add_column("Lang", style="dim", width=10)
    file_table.add_column("LOC", justify="right")
    file_table.add_column("Raw tok", justify="right")
    file_table.add_column("Proj tok", justify="right")
    file_table.add_column("Type", width=5, justify="center")

    top_files = sorted(snap.files, key=lambda x: x.lines, reverse=True)[:top_n]
    for i, f in enumerate(top_files, 1):
        lang_color = f.lang.color if f.lang else "white"
        lang_label = f.lang.name if f.lang else "?"
        ftype = "[blue]test[/]" if f.is_test else ("[dim]doc[/]" if f.is_doc else "[dim green]src[/]")
        reason = _proj_reason(f)
        proj_str = f"[bright_green]{_fmt_num(f.proj_tokens)}[/]" if reason is None else f"[dim]{_fmt_num(f.tokens)}[/]"
        file_table.add_row(
            str(i),
            f"[dim]{f.rel}[/]",
            f"[{lang_color}]{lang_label}[/]",
            f"[bright_white]{_fmt_num(f.lines)}[/]",
            f"[dim]{_fmt_num(f.tokens)}[/]",
            proj_str,
            ftype,
        )

    console.print(file_table)

    # ── Top directories ──
    console.print("[bold bright_white]  Top Directories[/]  [dim]by lines of code[/]")
    console.print()

    dir_table = Table(box=box.SIMPLE, show_header=True, header_style="dim", padding=(0, 1))
    dir_table.add_column("#", justify="right", style="dim", width=3)
    dir_table.add_column("Directory", min_width=20)
    dir_table.add_column("Files", justify="right", style="dim")
    dir_table.add_column("LOC", justify="right")
    dir_table.add_column("Share", min_width=24)

    sorted_dirs = sorted(snap.by_dir.items(), key=lambda x: x[1]["loc"], reverse=True)[:top_n]
    max_dir_loc = sorted_dirs[0][1]["loc"] if sorted_dirs else 1

    for i, (d, stats) in enumerate(sorted_dirs, 1):
        frac = stats["loc"] / max_dir_loc
        dir_table.add_row(
            str(i),
            f"[bright_white]{d}/[/]",
            _fmt_num(stats["files"]),
            f"[bright_cyan]{_fmt_num(stats['loc'])}[/]",
            f"[cyan]{_bar(frac, 22)}[/]",
        )

    console.print(dir_table)

    # ── Code health + Atelier projection + non-projectable ──
    bottom = Table.grid(expand=True, padding=(0, 1))
    bottom.add_column(ratio=1)
    bottom.add_column(ratio=1)
    bottom.add_column(ratio=1)

    # Health panel
    health_lines = [
        f"  [dim]Source files[/]   [bright_white]{_fmt_num(snap.source_files)}[/]  [dim]({code_ratio}% of total)[/]",
        f"  [dim]Test files  [/]   [bright_white]{_fmt_num(snap.test_files)}[/]  [dim]({test_ratio}% test coverage)[/]",
        f"  [dim]Doc files   [/]   [bright_white]{_fmt_num(snap.doc_files)}[/]",
        "",
        f"  [dim]Projectable files [/]  [bright_white]{_fmt_num(snap.large_files)}[/]",
    ]
    health_panel = Panel(
        "\n".join(health_lines),
        title="[bold]Code Profile[/]",
        border_style="dim",
        padding=(1, 2),
    )

    # Atelier projection panel
    saved_k = snap.proj_tokens_saved // 1000
    atelier_lines = [
        f"  [dim]Raw tokens      [/]  [white]{_fmt_num(total_k)}k[/]",
        f"  [dim]Projected tokens[/]  [bright_green]{_fmt_num(after_k)}k[/]",
        f"  [dim]Saved           [/]  [bright_green]{_fmt_num(saved_k)}k[/]  [dim]({save_pct}%)[/]",
        "",
        "  [dim]--files N  for per-file breakdown[/]",
    ]
    atelier_panel = Panel(
        "\n".join(atelier_lines),
        title="[bold bright_green]Projection Savings[/]",
        border_style="bright_green dim",
        padding=(1, 2),
    )

    # Non-projectable classification panel
    from collections import Counter

    reason_counts: Counter[str] = Counter()
    for f in snap.files:
        r = _proj_reason(f)
        if r is not None:
            reason_counts[r] += 1
    nonproj_lines: list[str] = []
    for reason, count in reason_counts.most_common():
        nonproj_lines.append(f"  [yellow]{reason:<22}[/]  [dim]{_fmt_num(count)} files[/]")
    if not nonproj_lines:
        nonproj_lines = ["  [dim]all files are projectable[/]"]
    nonproj_panel = Panel(
        "\n".join(nonproj_lines),
        title="[bold yellow]Non-projectable[/]",
        border_style="yellow dim",
        padding=(1, 2),
    )

    bottom.add_row(health_panel, atelier_panel, nonproj_panel)
    console.print(bottom)
    console.print()


# ---------------------------------------------------------------------------
# --files view
# ---------------------------------------------------------------------------


def _render_files(snap: ProjectSnapshot, limit: int) -> None:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    all_files = sorted(snap.files, key=lambda f: f.tokens, reverse=True)

    console.print()
    console.rule(f"[bold bright_white]> {snap.root.name}[/]  [dim]per-file token breakdown[/]")
    console.print()

    # ── File table ──
    tbl = Table(box=box.SIMPLE, show_header=True, header_style="dim", padding=(0, 1))
    tbl.add_column("#", justify="right", style="dim", width=4)
    tbl.add_column("File", min_width=38, no_wrap=False)
    tbl.add_column("Lang", width=11)
    tbl.add_column("LOC", justify="right")
    tbl.add_column("Raw tok", justify="right")
    tbl.add_column("Proj tok", justify="right")
    tbl.add_column("Saved", justify="right")
    tbl.add_column("Reason", style="dim")

    shown = all_files[:limit]
    for i, f in enumerate(shown, 1):
        reason = _proj_reason(f)
        lang_color = f.lang.color if f.lang else "dim white"
        lang_label = f.lang.name if f.lang else "?"
        raw = f.tokens
        proj = f.proj_tokens
        saved_pct = int((raw - proj) / max(1, raw) * 100)

        if reason is None:
            saved_str = f"[bright_green]-{saved_pct}%[/]"
            proj_str = f"[bright_green]{_fmt_num(proj)}[/]"
            reason_str = ""
        else:
            saved_str = "[dim]—[/]"
            proj_str = f"[dim]{_fmt_num(proj)}[/]"
            reason_str = f"[dim]{reason}[/]"

        tbl.add_row(
            str(i),
            f"[dim]{f.rel}[/]",
            f"[{lang_color}]{lang_label}[/]",
            _fmt_num(f.lines),
            _fmt_num(raw),
            proj_str,
            saved_str,
            reason_str,
        )

    console.print(tbl)
    if len(all_files) > limit:
        console.print(f"  [dim]… {len(all_files) - limit} more files not shown. Increase --files N to see more.[/]")
    console.print()

    # ── Non-projectable summary ──
    non_proj = [(f, _proj_reason(f)) for f in snap.files if _proj_reason(f) is not None]

    # Group by reason
    by_reason: dict[str, list[FileStats]] = defaultdict(list)
    for f, r in non_proj:
        by_reason[r].append(f)

    console.print("[bold bright_white]  Non-projectable files[/]  [dim]by skip reason[/]")
    console.print()

    reason_tbl = Table(box=box.SIMPLE, show_header=True, header_style="dim", padding=(0, 1))
    reason_tbl.add_column("Reason", min_width=22)
    reason_tbl.add_column("Files", justify="right")
    reason_tbl.add_column("Raw tokens", justify="right")
    reason_tbl.add_column("Notes", style="dim")

    reason_notes = {
        "no code structure (compact only)": "data/config/markup — whitespace-only savings",
        "unrecognized type": "extension not in language registry",
    }

    for reason, files in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        total_raw = sum(f.tokens for f in files)
        note = reason_notes.get(reason, "")
        reason_tbl.add_row(
            f"[yellow]{reason}[/]",
            _fmt_num(len(files)),
            _fmt_num(total_raw),
            note,
        )

    console.print(reason_tbl)

    # Detail drill-down: list top 10 non-projectable by token count
    if non_proj:
        console.print()
        console.print("  [dim]Top non-projectable files by token count:[/]")
        console.print()
        detail_tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        detail_tbl.add_column("File", style="dim", min_width=40)
        detail_tbl.add_column("Reason", style="yellow", width=20)
        detail_tbl.add_column("Tokens", justify="right", style="dim")

        for f, reason in sorted(non_proj, key=lambda x: -x[0].tokens)[:10]:
            detail_tbl.add_row(f.rel, reason or "", _fmt_num(f.tokens))
        console.print(detail_tbl)

    # Summary panel
    proj_count = snap.large_files
    nonproj_count = len(non_proj)
    proj_raw = snap.proj_tokens_total
    proj_after = snap.proj_tokens_after
    summary = Panel(
        f"  [dim]Projectable[/]      [bright_green]{_fmt_num(proj_count)}[/] files  ·  "
        f"[white]{_fmt_num(proj_raw // 1000)}k[/] raw → [bright_green]{_fmt_num(proj_after // 1000)}k[/] projected  "
        f"[dim]({int(snap.proj_tokens_saved / max(1, proj_raw) * 100)}% saved)[/]\n"
        f"  [dim]Non-projectable[/]  [yellow]{_fmt_num(nonproj_count)}[/] files  ·  "
        f"[dim]read at full token cost[/]",
        title="[bold]Projection Summary[/]",
        border_style="dim",
        padding=(0, 2),
    )
    console.print(summary)
    console.print()


# ---------------------------------------------------------------------------
# Projection engine — approximate what Atelier's outline/read tool produces
# ---------------------------------------------------------------------------


def _project_python(lines: list[str]) -> str:
    """Extract Python outline: imports, class/def signatures, docstrings."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Always keep imports and top-level blank lines
        if stripped.startswith(("import ", "from ", "@")) or not stripped:
            out.append(line.rstrip())
            i += 1
            continue

        # Class or function definition
        if stripped.startswith(("def ", "class ", "async def ")):
            out.append(line.rstrip())
            i += 1
            # Include immediate docstring
            if i < len(lines):
                ds = lines[i].strip()
                if ds.startswith('"""') or ds.startswith("'''"):
                    quote = ds[:3]
                    out.append(lines[i].rstrip())
                    if not ds.endswith(quote) or len(ds) == 3:  # multi-line
                        i += 1
                        while i < len(lines) and quote not in lines[i]:
                            out.append(lines[i].rstrip())
                            i += 1
                        if i < len(lines):
                            out.append(lines[i].rstrip())
                            i += 1
                    else:
                        i += 1
            # Skip body, count skipped lines
            body_start = i
            while i < len(lines):
                next_indent = len(lines[i]) - len(lines[i].lstrip())
                if lines[i].strip() and next_indent <= indent:
                    break
                i += 1
            skipped = i - body_start
            if skipped > 0:
                pad = " " * (indent + 4)
                out.append(f"{pad}# ... {skipped} lines")
            continue

        # Top-level assignments / constants
        if indent == 0 and "=" in stripped and not stripped.startswith("#"):
            out.append(line.rstrip())
            i += 1
            continue

        i += 1  # skip all other lines

    return "\n".join(out)


def _project_ts(lines: list[str]) -> str:
    """Extract TypeScript/JavaScript outline: imports, exports, signatures."""
    out: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if not s:
            out.append("")
            i += 1
            continue

        # Imports always kept
        if s.startswith(("import ", "export {", "export type", "export *", "require(")):
            out.append(line.rstrip())
            i += 1
            continue

        # Interfaces and type aliases — keep fully (usually short)
        if s.startswith(("interface ", "type ", "export interface", "export type")):
            out.append(line.rstrip())
            i += 1
            depth = s.count("{") - s.count("}")
            while depth > 0 and i < len(lines):
                out.append(lines[i].rstrip())
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
            continue

        # Function / class / const arrow signatures — keep signature, skip body
        is_sig = (
            s.startswith(
                (
                    "function ",
                    "async function",
                    "class ",
                    "export class",
                    "export function",
                    "export async",
                    "export default",
                )
            )
            or ("=> {" in s and s.startswith(("const ", "let ", "export const")))
            or (s.startswith(("const ", "let ")) and ("function" in s or "=>" in s))
        )
        if is_sig:
            out.append(line.rstrip())
            i += 1
            # Count and skip body braces
            depth = line.count("{") - line.count("}")
            body_lines = 0
            while depth > 0 and i < len(lines):
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
                body_lines += 1
            if body_lines > 1:
                out.append(f"  // ... {body_lines} lines")
            continue

        i += 1  # skip other lines

    return "\n".join(out)


def _project_c(lines: list[str]) -> str:
    """Extract C/C++ outline: preprocessor, typedefs, structs, function signatures."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            out.append("")
            i += 1
            continue

        # Preprocessor — always keep (handle backslash continuation)
        if stripped.startswith("#"):
            out.append(line.rstrip())
            i += 1
            while line.rstrip().endswith("\\") and i < len(lines):
                line = lines[i]
                out.append(line.rstrip())
                i += 1
            continue

        # Block comments at top level — keep
        if stripped.startswith("/*"):
            out.append(line.rstrip())
            i += 1
            if "*/" not in stripped:
                while i < len(lines):
                    out.append(lines[i].rstrip())
                    if "*/" in lines[i]:
                        i += 1
                        break
                    i += 1
            continue

        if stripped.startswith("//"):
            out.append(line.rstrip())
            i += 1
            continue

        # typedef / struct / union / enum — keep declaration including body
        if stripped.startswith(("typedef ", "struct ", "union ", "enum ")):
            out.append(line.rstrip())
            i += 1
            depth = line.count("{") - line.count("}")
            while i < len(lines):
                out.append(lines[i].rstrip())
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
                if depth <= 0:
                    break
            continue

        # Function-like: collect signature lines until { or ;
        sig: list[str] = [line.rstrip()]
        j = i + 1
        has_brace = "{" in line
        has_semi = ";" in line and "{" not in line

        if not has_brace and not has_semi:
            while j < len(lines) and j < i + 12:
                nxt = lines[j]
                sig.append(nxt.rstrip())
                if "{" in nxt:
                    has_brace = True
                    break
                if ";" in nxt:
                    has_semi = True
                    break
                j += 1

        if has_brace:
            for sl in sig:
                out.append(sl)
            i = j + 1
            depth = sum(ln.count("{") - ln.count("}") for ln in sig)
            body_start = i
            while depth > 0 and i < len(lines):
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
            skipped = i - body_start
            if skipped > 0:
                out.append(f"  /* ... {skipped} lines */")
            continue

        # Declaration or unknown — keep as-is
        out.append(line.rstrip())
        i += 1

    return "\n".join(out)


def _build_projection(text: str, lang: LangDef) -> str:
    lines = text.splitlines()
    if lang.name == "Python":
        return _project_python(lines)
    if lang.name in ("TypeScript", "JavaScript", "Astro"):
        return _project_ts(lines)
    if lang.name in ("C/C++", "Rust", "Go", "Java", "C#", "Kotlin", "Scala", "PHP", "Ruby", "Swift"):
        return _project_c(lines)  # brace-based fallback works for all C-family
    # For Shell, TOML, etc — just return as-is (they're usually short config/scripts)
    return text


# ---------------------------------------------------------------------------
# --diff view
# ---------------------------------------------------------------------------


def _compact_whitespace(text: str) -> str:
    """Apply Atelier's real compact projection: strip trailing whitespace, collapse blank runs."""
    import re

    out = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


def _render_diff(file_path: Path) -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.table import Table

    console = Console()

    ext = file_path.suffix.lower()
    lang = _EXT_TO_LANG.get(ext)

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        console.print(f"[red]Cannot read file: {e}[/]")
        return

    if lang is None:
        console.print(f"[yellow]Unrecognized file type: {ext}[/]")
        return

    raw_lines = text.splitlines()
    loc = len(raw_lines)
    reason = _proj_reason(
        FileStats(
            path=file_path,
            rel=str(file_path),
            lang=lang,
            size_bytes=file_path.stat().st_size,
            lines=loc,
            code_lines=0,
            comment_lines=0,
            blank_lines=0,
            is_test=False,
            is_doc=False,
        )
    )

    # Choose projection mode matching Atelier's actual behaviour
    use_outline = reason is None  # outline-eligible: code file >= 200 LOC
    if use_outline:
        projected = _build_projection(text, lang)
        mode_label = "[bright_green]Outline[/] [dim](structure only · bodies omitted)[/]"
        mode_note = "LLM can fetch any body via read(path, range='Lx-Ly')"
    else:
        projected = _compact_whitespace(text)
        mode_label = "[yellow]Compact[/] [dim](whitespace-normalized · full body)[/]"
        mode_note = reason or ""

    raw_lines = text.splitlines()
    proj_lines = projected.splitlines()
    raw_tok = _est_tokens(len(text.encode()))
    proj_tok = _est_tokens(len(projected.encode()))
    saved_pct = int((raw_tok - proj_tok) / max(1, raw_tok) * 100)

    lexer_map = {
        "Python": "python",
        "TypeScript": "typescript",
        "JavaScript": "javascript",
        "Rust": "rust",
        "Go": "go",
        "Astro": "astro",
        "Shell": "bash",
        "C/C++": "c",
        "Java": "java",
        "Ruby": "ruby",
        "C#": "csharp",
    }
    lexer = lexer_map.get(lang.name, "text")

    console.print()
    console.rule(f"[bold bright_white]{file_path.name}[/]  [dim]{lang.name}  ·  {loc} lines[/]")
    console.print(f"  Mode: {mode_label}")
    if mode_note:
        console.print(f"  [dim]{mode_note}[/]")
    console.print()

    stats = Table.grid(expand=True)
    stats.add_column(justify="center")
    stats.add_column(justify="center")
    stats.add_column(justify="center")

    def _chip(label: str, value: str, color: str) -> Panel:
        return Panel(f"[bold {color}]{value}[/]\n[dim]{label}[/]", border_style="dim", padding=(0, 2))

    stats.add_row(
        _chip("Raw lines", f"{len(raw_lines):,}", "white"),
        _chip("Projected lines", f"{len(proj_lines):,}", "bright_green"),
        _chip("Tokens saved", f"-{saved_pct}%  ({raw_tok:,} → {proj_tok:,})", "bright_green"),
    )
    console.print(stats)
    console.print()

    raw_syntax = Syntax(text, lexer, theme="monokai", line_numbers=True, word_wrap=False)
    proj_syntax = Syntax(projected, lexer, theme="monokai", line_numbers=True, word_wrap=False)

    split = Table.grid(expand=True, padding=(0, 1))
    split.add_column(ratio=1)
    split.add_column(ratio=1)
    split.add_row(
        Panel(
            raw_syntax,
            title=f"[dim]Raw ({len(raw_lines)} lines · {raw_tok:,} tok)[/]",
            border_style="dim",
            padding=(0, 0),
        ),
        Panel(
            proj_syntax,
            title=f"[bright_green]{'Outline' if use_outline else 'Compact'} "
            f"({len(proj_lines)} lines · {proj_tok:,} tok)[/]",
            border_style="bright_green dim",
            padding=(0, 0),
        ),
    )
    console.print(split)
    console.print()


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command("project")
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--top", default=5, show_default=True, type=int, help="Number of top entries per table.")
@click.option(
    "--files",
    "files_limit",
    default=0,
    type=int,
    metavar="N",
    help="Show per-file token breakdown table (top N files by token count). 0 = off.",
)
@click.option(
    "--diff",
    "diff_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Show raw vs projected outline for a specific file.",
)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
@click.pass_context
def project_cmd(
    ctx: click.Context, path: Path, top: int, files_limit: int, diff_path: Path | None, as_json: bool
) -> None:
    """Scan a project and show language breakdown, top files, directories, and Atelier savings.

    \b
    Examples:
      atelier project               # overview of cwd
      atelier project --files 30    # per-file token table (top 30 by tokens)
      atelier project --diff src/foo.py   # raw vs projected side-by-side
      atelier project --json        # raw JSON
    """
    if diff_path is not None:
        _render_diff(diff_path)
        return

    root = path.resolve()
    snap = _scan(root)

    if as_json:
        click.echo(json.dumps(snap.to_json(), indent=2))
        return

    if files_limit > 0:
        _render_files(snap, limit=files_limit)
    else:
        _render(snap, top_n=top)
