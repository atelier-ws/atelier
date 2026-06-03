from __future__ import annotations

import json
from pathlib import Path

from atelier.core.capabilities.default_definitions import build_default_registry
from atelier.core.capabilities.workflow_defaults import bootstrap_default_definitions

ROOT = Path(__file__).resolve().parents[2]
HOST_FACING_ROLES = {"code", "explore", "execute", "plan", "research", "review", "solve"}
REQUIRED_ROLES = HOST_FACING_ROLES | {"general"}


def test_default_registry_contains_required_roles() -> None:
    registry = build_default_registry(ROOT)

    assert REQUIRED_ROLES <= set(registry.roles)

    general = registry.roles["general"]
    assert general.prompt_source is None
    assert general.prompt_body
    assert general.host_projections == ()
    assert general.model_default
    assert general.max_turns > 0
    assert general.max_tokens > 0


def test_host_facing_roles_stay_sourced_from_mode_docs() -> None:
    registry = build_default_registry(ROOT)

    for role_id in sorted(HOST_FACING_ROLES):
        role = registry.roles[role_id]
        assert role.prompt_source is not None
        assert role.prompt_source.as_posix().endswith(f"docs/agent-os/modes/{role_id}.md")
        body = registry.render_prompt(role_id, ROOT)
        assert "Eval" not in body
        assert f"# {role_id.replace('-', ' ').title()} mode" in body


def test_registry_exposes_owned_workflows_and_solver_contracts() -> None:
    registry = build_default_registry(ROOT)

    review = registry.roles["review"]
    assert review.workflow_usage == ("owned-execute-review-loop", "owned-benchmark-solver")
    assert review.read_mode_hint == "exact"
    assert review.review_contract is not None
    assert review.review_contract.require_first_hand_evidence is True
    assert review.review_contract.verdict_format == "json-block"
    assert review.review_contract.default_verdict == "NEEDS_FIX"
    assert {"edit", "write", "delete"} <= set(review.tool_policy.denied_actions)

    owned_loop = registry.workflows["owned-execute-review-loop"]
    assert owned_loop.stem_prompt_id == "owned-stem-system"
    assert [step.step_id for step in owned_loop.steps] == [
        "explore",
        "plan",
        "execute",
        "review",
        "refine",
    ]
    assert owned_loop.steps[1].fork_from == "explore"
    assert owned_loop.steps[3].fork_from == "plan"
    assert owned_loop.steps[4].fork_from == "plan"
    assert owned_loop.steps[0].read_mode_hint == "minified"
    assert owned_loop.steps[2].read_mode_hint == "exact"
    assert owned_loop.steps[0].effort == "adaptive"
    assert owned_loop.steps[2].effort in {"medium", "high"}

    solver_loop = registry.workflows["owned-benchmark-solver"]
    assert solver_loop.stem_prompt_id == "owned-stem-system"
    assert [step.step_id for step in solver_loop.steps] == [
        "explore",
        "plan",
        "execute",
        "review",
        "retry",
    ]
    assert solver_loop.steps[4].fork_from == "review"
    assert solver_loop.steps[4].phase_prompt_id == "solver-retry"

    profile = registry.benchmark_profiles["terminalbench-owned-solver"]
    assert profile.role_id == "solve"
    assert profile.workflow_id == "owned-benchmark-solver"
    assert profile.retry_limit == 2
    assert any("stderr" in rule.lower() for rule in profile.command_rules)
    assert any("generator" in rule.lower() for rule in profile.command_rules)
    assert any("failed command" in rule.lower() for rule in profile.command_rules)


def test_registry_host_projections_match_current_surface_set() -> None:
    registry = build_default_registry(ROOT)

    surfaced = {"code", "explore", "execute", "plan", "research", "review", "solve"}
    assert set(registry.surfaced_role_ids("shared_skill")) == surfaced
    assert set(registry.surfaced_role_ids("claude_agent")) == surfaced
    assert set(registry.surfaced_role_ids("claude_agent_dev")) == surfaced
    assert set(registry.surfaced_role_ids("opencode_agent")) == surfaced
    assert set(registry.surfaced_role_ids("antigravity_agent")) == surfaced
    assert "general" not in set(registry.surfaced_role_ids("shared_skill"))


def test_bootstrap_default_definitions_creates_then_skips_missing_defaults(tmp_path: Path) -> None:
    first = bootstrap_default_definitions(tmp_path, repo_root=ROOT)
    first_statuses = {entry.status for entry in first.entries}
    assert "created" in first_statuses

    manifest_path = tmp_path / "defaults" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "roles" in manifest
    assert "owned-execute-review-loop" in manifest["workflows"]
    assert "terminalbench-owned-solver" in manifest["benchmark_profiles"]

    second = bootstrap_default_definitions(tmp_path, repo_root=ROOT)
    assert second.entries
    assert {entry.status for entry in second.entries} == {"skipped"}


def test_bootstrap_default_definitions_reports_changed_and_invalid_targets(tmp_path: Path) -> None:
    bootstrap_default_definitions(tmp_path, repo_root=ROOT)

    manifest_path = tmp_path / "defaults" / "manifest.json"
    manifest_path.write_text('{"user":"changed"}\n', encoding="utf-8")

    changed = bootstrap_default_definitions(tmp_path, repo_root=ROOT)
    assert any(entry.path == manifest_path and entry.status == "changed" for entry in changed.entries)

    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("x", encoding="utf-8")
    invalid = bootstrap_default_definitions(invalid_root, repo_root=ROOT)
    assert any(entry.status == "invalid" for entry in invalid.entries)
