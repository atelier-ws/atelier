from __future__ import annotations

import re
from pathlib import Path


def test_readme_benchmarks_do_not_publish_legacy_percentage_claims() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    benchmark_section = text.split("## Benchmarks", 1)[1].split("## Development", 1)[0]
    assert "81%" not in benchmark_section
    assert "70%" not in benchmark_section
    assert "80%" not in benchmark_section
    assert not re.search(r"\b[5-9]\d\s*%", benchmark_section)


def test_readme_points_to_honest_replay_benchmark() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    assert "make bench-savings-honest" in text
    assert "docs/benchmarks/v3-honest-savings.md" in text
