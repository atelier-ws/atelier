from __future__ import annotations

import json
from pathlib import Path

from atelier.core.capabilities.lesson_promotion import LessonPromoterCapability
from atelier.core.foundation.models import ReasonBlock, Trace
from atelier.core.foundation.store import ReasoningStore


def _fixture_path() -> Path:
    return Path("tests/fixtures/200_failed_traces.jsonl")


def test_lesson_promotion_precision_on_fixture(tmp_path: Path) -> None:
    store = ReasoningStore(tmp_path / ".atelier")
    store.init()
    # Seed one existing block so edit_block candidates have a meaningful target.
    store.upsert_block(
        ReasonBlock(
            id="rb-permission-precheck",
            title="Permission precheck before writes",
            domain="coding",
            triggers=["permission", "write"],
            situation="Write operations fail when paths are not writable.",
            dead_ends=["permission denied"],
            procedure=["Verify write permissions for destination paths before mutation."],
        ),
        write_markdown=False,
    )

    promoter = LessonPromoterCapability(store)

    predicted = 0
    correct = 0

    with _fixture_path().open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            expected_kind = row.pop("expected_kind", "")
            trace = Trace.model_validate(row)
            store.record_trace(trace, write_json=False)
            candidate = promoter.ingest_trace(trace)
            if candidate is None:
                continue
            predicted += 1
            if expected_kind and candidate.kind == expected_kind:
                correct += 1

    assert predicted > 0
    precision = correct / predicted
    assert precision >= 0.7, f"precision={precision:.3f}, correct={correct}, predicted={predicted}"
