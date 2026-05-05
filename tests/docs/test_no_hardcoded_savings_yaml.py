from __future__ import annotations

from pathlib import Path


def test_v2_savings_yaml_does_not_claim_a_percentage_target() -> None:
    text = Path("benchmarks/swe/prompts_11.yaml").read_text(encoding="utf-8").lower()
    forbidden = ["reduction_pct", "50 %", "50%", "actual:", "target:"]
    assert not any(term in text for term in forbidden)
