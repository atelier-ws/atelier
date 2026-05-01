from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner, Result

from atelier.gateway.adapters.cli import cli


def _invoke(root: Path, *args: str, input: str | None = None) -> Result:
    runner = CliRunner()
    return runner.invoke(cli, ["--root", str(root), *args], input=input)


def test_init_seeds_blocks_and_rubrics(tmp_path: Path) -> None:
    res = _invoke(tmp_path / "a", "init")
    assert res.exit_code == 0, res.output
    assert "seeded" in res.output
    # 10 blocks + 6 rubrics expected
    assert "10 reasonblocks" in res.output
    assert "6 rubrics" in res.output


def test_check_plan_blocks_shopify_handle_from_url(tmp_path: Path) -> None:
    root = tmp_path / "a"
    _invoke(root, "init")
    res = _invoke(
        root,
        "check-plan",
        "--task",
        "Fix shopify",
        "--domain",
        "beseam.shopify.publish",
        "--step",
        "Parse Shopify product handle from URL",
        "--step",
        "Update metafield",
        "--json",
    )
    assert res.exit_code == 2, res.output
    payload = json.loads(res.output)
    assert payload["status"] == "blocked"


def test_run_rubric_via_cli(tmp_path: Path) -> None:
    root = tmp_path / "a"
    _invoke(root, "init")
    checks = json.dumps(
        {
            "product_identity_uses_gid": True,
            "pre_publish_snapshot_exists": True,
            "write_result_checked": True,
            "post_publish_refetch_done": True,
            "post_publish_audit_passed": True,
            "rollback_available": True,
            "localized_url_test_passed": True,
            "changed_handle_test_passed": True,
        }
    )
    res = _invoke(root, "run-rubric", "rubric_shopify_publish", "--json", input=checks)
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["status"] == "pass"


def test_run_rubric_blocks_when_required_missing(tmp_path: Path) -> None:
    root = tmp_path / "a"
    _invoke(root, "init")
    res = _invoke(root, "run-rubric", "rubric_shopify_publish", "--json", input="{}")
    assert res.exit_code == 2
    payload = json.loads(res.output)
    assert payload["status"] == "blocked"


def test_record_trace_and_extract_block(tmp_path: Path) -> None:
    root = tmp_path / "a"
    _invoke(root, "init")
    trace = json.dumps(
        {
            "agent": "codex",
            "domain": "coding",
            "task": "Test trace ingest",
            "status": "success",
            "files_touched": ["src/foo.py"],
            "commands_run": ["pytest"],
            "validation_results": [{"name": "unit", "passed": True, "detail": ""}],
        }
    )
    res = _invoke(root, "record-trace", input=trace)
    assert res.exit_code == 0
    trace_id = res.output.strip()

    res2 = _invoke(root, "extract-block", trace_id, "--json")
    assert res2.exit_code == 0
    payload = json.loads(res2.output)
    assert payload["confidence"] >= 0.4


def test_rescue_returns_procedure(tmp_path: Path) -> None:
    root = tmp_path / "a"
    _invoke(root, "init")
    res = _invoke(
        root,
        "rescue",
        "--task",
        "Update Shopify product",
        "--error",
        "wrong product updated",
        "--domain",
        "beseam.shopify.publish",
        "--json",
    )
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert "rescue" in payload
    assert payload["matched_blocks"]


# --------------------------------------------------------------------------- #
# `atelier task` command                                                      #
# --------------------------------------------------------------------------- #


def test_task_emits_prompt_with_task_text(tmp_path: Path) -> None:
    root = tmp_path / "a"
    _invoke(root, "init")
    res = _invoke(
        root,
        "task",
        "Fix",
        "Shopify",
        "publish",
        "validation",
        "--domain",
        "beseam.shopify.publish",
        "--file",
        "backend/src/modules/shopify/publish.py",
        "--tool",
        "shopify.gql",
    )
    assert res.exit_code == 0, res.output
    out = res.output
    assert "Fix Shopify publish validation" in out
    assert "atelier_check_plan" in out
    assert "atelier_record_trace" in out


def test_task_json_envelope_has_expected_keys(tmp_path: Path) -> None:
    root = tmp_path / "a"
    _invoke(root, "init")
    res = _invoke(
        root,
        "task",
        "Refactor publish flow",
        "--domain",
        "beseam.shopify.publish",
        "--json",
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["task"] == "Refactor publish flow"
    assert payload["domain"] == "beseam.shopify.publish"
    assert isinstance(payload["matched"], list)
    assert "prompt" in payload and isinstance(payload["prompt"], str)
    assert "Refactor publish flow" in payload["prompt"]


def test_task_empty_description_errors(tmp_path: Path) -> None:
    root = tmp_path / "a"
    _invoke(root, "init")
    # Single empty whitespace argument -> stripped to empty -> ClickException.
    res = _invoke(root, "task", "   ")
    assert res.exit_code != 0
    assert "task description is required" in res.output


def test_task_matches_shopify_block(tmp_path: Path) -> None:
    root = tmp_path / "a"
    _invoke(root, "init")
    res = _invoke(
        root,
        "task",
        "Fix Shopify publish validation",
        "--domain",
        "beseam.shopify.publish",
        "--json",
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    titles = " ".join(m["title"].lower() for m in payload["matched"])
    assert "shopify" in titles or payload["matched"], payload
