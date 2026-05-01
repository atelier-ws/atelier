"""
Documentation integrity tests.

Verifies:
- All markdown files in docs/ are parseable
- All internal links in docs/ resolve to real files
- README.md contains required sections
"""

from __future__ import annotations

import re
from pathlib import Path

DOCS_ROOT = Path(__file__).parent.parent.parent / "docs"
README = Path(__file__).parent.parent.parent / "README.md"

REQUIRED_README_SECTIONS = [
    "What Atelier is not",
    "Quickstart",
    "MCP Server",
]

# Internal link pattern: [text](path.md) or [text](path.md#anchor)
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def collect_markdown_files() -> list[Path]:
    return sorted(DOCS_ROOT.rglob("*.md"))


def test_docs_directory_exists() -> None:
    assert DOCS_ROOT.exists(), f"docs/ directory missing at {DOCS_ROOT}"
    assert DOCS_ROOT.is_dir()


def test_all_markdown_files_are_parseable() -> None:
    files = collect_markdown_files()
    assert len(files) > 0, "No markdown files found in docs/"
    for f in files:
        content = f.read_text(encoding="utf-8")
        assert isinstance(content, str), f"{f}: could not read as text"
        assert len(content) > 0, f"{f}: empty file"


def test_required_doc_files_exist() -> None:
    required = [
        "quickstart.md",
        "installation.md",
        "cli.md",
        "troubleshooting.md",
        "README.md",
        "hosts/claude-code.md",
        "hosts/copilot.md",
        "hosts/codex.md",
        "hosts/opencode.md",
        "hosts/gemini-cli.md",
        "copy-paste/copilot-instructions.md",
        "engineering/architecture.md",
        "engineering/storage.md",
        "engineering/service.md",
        "engineering/mcp.md",
        "engineering/workers.md",
        "engineering/security.md",
        "engineering/evals.md",
        "engineering/dogfooding.md",
        "engineering/contributing.md",
    ]
    for rel in required:
        path = DOCS_ROOT / rel
        assert path.exists(), f"Missing required doc: docs/{rel}"


def test_all_internal_links_resolve() -> None:
    broken: list[str] = []
    for md_file in collect_markdown_files():
        content = md_file.read_text(encoding="utf-8")
        for _text, href in LINK_PATTERN.findall(content):
            # Skip external links
            if href.startswith("http://") or href.startswith("https://"):
                continue
            # Strip anchors
            href_path = href.split("#")[0]
            if not href_path:
                continue
            target = (md_file.parent / href_path).resolve()
            if not target.exists():
                broken.append(f"{md_file.relative_to(DOCS_ROOT.parent)}: [{_text}]({href})")
    assert not broken, "Broken internal links:\n" + "\n".join(broken)


def test_readme_contains_required_sections() -> None:
    assert README.exists(), f"README.md not found at {README}"
    content = README.read_text(encoding="utf-8")
    for section in REQUIRED_README_SECTIONS:
        assert section in content, f"README.md missing section: {section!r}"
