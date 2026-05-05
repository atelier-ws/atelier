from __future__ import annotations

from pathlib import Path

REQUIRED_TOPICS = {
    "stub_embedding",
    "make bench-savings-honest",
    "ATELIER_MEMORY_BACKEND=letta",
    "consolidate",
}


REQUIRED_MATRIX_AREAS = {
    "Runtime embeddings",
    "Savings benchmark",
    "Memory backend",
    "Sleeptime summaries",
    "Tool output",
    "Repo context",
    "Memory updates",
}


def test_v2_to_v3_migration_guide_covers_operator_steps() -> None:
    text = Path("docs/migrations/v2-to-v3.md").read_text(encoding="utf-8")

    for topic in REQUIRED_TOPICS:
        assert topic in text


def test_v2_to_v3_deprecation_matrix_covers_changed_surfaces() -> None:
    text = Path("docs/migrations/v2-to-v3-deprecation-matrix.md").read_text(encoding="utf-8")

    for area in REQUIRED_MATRIX_AREAS:
        assert area in text


def test_readme_and_changelog_link_to_migration_docs() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert "docs/migrations/v2-to-v3.md" in readme
    assert "docs/migrations/v2-to-v3.md" in changelog
    assert "docs/migrations/v2-to-v3-deprecation-matrix.md" in changelog
