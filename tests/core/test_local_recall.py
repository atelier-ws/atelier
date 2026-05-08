from __future__ import annotations

import json
from pathlib import Path

from atelier.core.capabilities.local_recall import (
    DIM,
    discover_transcripts,
    recall_transcripts,
    vectorize,
)


def test_local_recall_discovers_and_ranks_transcripts(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)
    transcript = project / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"message": {"content": "We fixed the sqlite auto limit behavior in the SQL tool."}}),
                json.dumps({"message": {"content": "Unrelated status line note."}}),
            ]
        ),
        encoding="utf-8",
    )

    assert discover_transcripts(tmp_path) == [transcript]
    result = recall_transcripts("sqlite auto limit", config_dir=tmp_path)
    assert result["matches"]
    assert "sqlite auto limit" in result["content"][0]["text"].lower()
    assert len(vectorize("hello")) == DIM