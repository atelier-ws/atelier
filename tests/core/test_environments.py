"""Tests for environments loading and matching."""

from __future__ import annotations

from atelier.core.foundation.environments import (
    find_forbidden_violations,
    load_packaged_environments,
    match_environments,
)


def test_packaged_environments_load_all_six() -> None:
    envs = load_packaged_environments()
    ids = {e.id for e in envs}
    assert {
        "env_coding_general",
        "env_shopify_publish",
        "env_pdp_schema",
        "env_catalog_fix",
        "env_ai_referral_tracker",
        "env_audit_service",
    }.issubset(ids)


def test_shopify_env_blocks_forbidden_handle_plan() -> None:
    envs = [e for e in load_packaged_environments() if e.id == "env_shopify_publish"]
    plan = ["Parse_product_handle_from_url for product"]
    violations = find_forbidden_violations(plan, envs)
    assert violations
    env, _step, phrase = violations[0]
    assert env.id == "env_shopify_publish"
    assert "handle" in phrase


def test_match_environments_by_domain_prefix() -> None:
    envs = load_packaged_environments()
    matches = match_environments(
        task="Publish a product to Shopify",
        domain="shopify.publish",
        environments=envs,
    )
    assert any(e.id == "env_shopify_publish" for e in matches)
