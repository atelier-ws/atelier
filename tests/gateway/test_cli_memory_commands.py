from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from atelier.gateway.adapters.cli import cli


def test_cli_memory_upsert_and_get_round_trip(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    runner = CliRunner()

    upsert = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "memory",
            "upsert",
            "--agent-id",
            "atelier:code",
            "--label",
            "scratch",
            "--value",
            "hello",
            "--pinned",
        ],
    )
    assert upsert.exit_code == 0, upsert.output
    payload = json.loads(upsert.output)
    assert payload["version"] == 1

    get = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "memory",
            "get",
            "--agent-id",
            "atelier:code",
            "--label",
            "scratch",
            "--json",
        ],
    )
    assert get.exit_code == 0, get.output
    block = json.loads(get.output)
    assert block["id"] == payload["id"]
    assert block["value"] == "hello"
    assert block["pinned"] is True


def test_cli_memory_upsert_reads_value_from_file(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    value_file = tmp_path / "value.md"
    value_file.write_text("file-backed memory", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "memory",
            "upsert",
            "--agent-id",
            "atelier:code",
            "--label",
            "from-file",
            "--value",
            f"@{value_file}",
        ],
    )
    assert result.exit_code == 0, result.output

    get = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "memory",
            "get",
            "--agent-id",
            "atelier:code",
            "--label",
            "from-file",
            "--json",
        ],
    )
    assert json.loads(get.output)["value"] == "file-backed memory"


def test_cli_memory_upsert_rejects_secret_from_stdin(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(tmp_path / ".atelier"),
            "memory",
            "upsert",
            "--agent-id",
            "t",
            "--label",
            "leak",
            "--value",
            "@/dev/stdin",
        ],
        input="AKIAIOSFODNN7EXAMPLE secretvalue",
    )

    assert result.exit_code != 0
    assert "likely secret leakage" in result.output
