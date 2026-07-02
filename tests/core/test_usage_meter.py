"""Unit tests for the local billing usage meter.

The meter (:func:`compute_usage_meter` / :func:`refresh_subscription_meter` in
``plugin_runtime``) prices trailing-window spend from the canonical per-session
savings ledger and compares it to the plan's ``monthlyLimitInUsd``. It is
non-blocking: it only annotates the subscription and produces ``subscription.json``
for the statusline warning surface (``_resolve_status_text``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atelier.core.capabilities import plugin_runtime as pr
from atelier.core.capabilities.savings_summary import _find_savings_sidecar, _resolve_status_text


@pytest.fixture()
def atelier_root(tmp_path: Path) -> Path:
    root = tmp_path / ".atelier"
    root.mkdir()
    return root


def _seed_ledger(root: Path, session_id: str, *, est_cost: float, saved: float) -> None:
    """Write a per-session savings.jsonl the windowed aggregator understands.

    A ``session_end`` row supplies the realized spend (``est_cost_usd``); a
    normal row supplies pre-priced context savings (``cost_saved_usd``).
    """
    sidecar = _find_savings_sidecar(session_id, root)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "ts": pr._iso_now(),
            "session_id": session_id,
            "tokens": 1000,
            "calls": 1,
            "cost_saved_usd": saved,
            "model": "claude-sonnet-4-5",
        },
        {"ts": pr._iso_now(), "session_id": session_id, "kind": "session_end", "est_cost_usd": est_cost},
    ]
    sidecar.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_no_limit_reports_spend_but_never_warns(atelier_root: Path) -> None:
    _seed_ledger(atelier_root, "s", est_cost=999.0, saved=1.0)
    sub = pr.compute_usage_meter(atelier_root, subscription={"monthlyLimitInUsd": 0.0})
    assert sub["monthlySpendInUsd"] == pytest.approx(999.0)
    assert sub["monthlySavingsInUsd"] == pytest.approx(1.0)
    # No limit configured -> reported but never blocking/warning.
    assert sub["warning"] is False
    assert sub["overLimit"] is False
    assert sub["remainingUsd"] is None
    assert sub["usageFraction"] == 0.0


def test_below_warn_threshold(atelier_root: Path) -> None:
    _seed_ledger(atelier_root, "s", est_cost=2.0, saved=0.9)
    sub = pr.compute_usage_meter(atelier_root, subscription={"monthlyLimitInUsd": 5.0})
    assert sub["monthlySpendInUsd"] == pytest.approx(2.0)
    assert sub["usageFraction"] == pytest.approx(0.4)
    assert sub["remainingUsd"] == pytest.approx(3.0)
    assert sub["warning"] is False
    assert sub["overLimit"] is False


def test_warning_band(atelier_root: Path) -> None:
    # 84% of the $5 limit -> at/over the 80% warn fraction, not yet over.
    _seed_ledger(atelier_root, "s", est_cost=4.2, saved=1.0)
    sub = pr.compute_usage_meter(atelier_root, subscription={"monthlyLimitInUsd": 5.0})
    assert sub["warning"] is True
    assert sub["overLimit"] is False
    assert "Approaching" in sub["message"]


def test_over_limit(atelier_root: Path) -> None:
    _seed_ledger(atelier_root, "s", est_cost=6.0, saved=2.0)
    sub = pr.compute_usage_meter(atelier_root, subscription={"monthlyLimitInUsd": 5.0})
    assert sub["overLimit"] is True
    assert sub["warning"] is True
    assert sub["remainingUsd"] == 0.0
    assert sub["usageFraction"] == pytest.approx(1.2)
    assert "reached" in sub["message"]


def test_warn_boundary_is_inclusive(atelier_root: Path) -> None:
    # Exactly 80% must warn (>= comparison), exactly 100% must be over.
    _seed_ledger(atelier_root, "s", est_cost=4.0, saved=0.0)
    sub = pr.compute_usage_meter(atelier_root, subscription={"monthlyLimitInUsd": 5.0})
    assert sub["warning"] is True and sub["overLimit"] is False


def test_default_trial_has_no_limit_and_never_warns(atelier_root: Path) -> None:
    # The source-available free core stamps no cap: the default trial has
    # monthlyLimitInUsd == 0.0 and the meter is report-only (never warns).
    _seed_ledger(atelier_root, "s", est_cost=999.0, saved=1.0)
    pr.claim_anonymous_trial(atelier_root)
    pr.refresh_subscription_meter(atelier_root)
    persisted = json.loads((atelier_root / "subscription.json").read_text())
    assert persisted["monthlyLimitInUsd"] == 0.0
    assert persisted["warning"] is False
    assert persisted["overLimit"] is False
    assert persisted["remainingUsd"] is None


def test_refresh_persists_and_statusline_surfaces_warning(atelier_root: Path) -> None:
    _seed_ledger(atelier_root, "s", est_cost=6.0, saved=2.0)
    pr.claim_anonymous_trial(atelier_root, monthly_limit_usd=5.0)
    metered = pr.refresh_subscription_meter(atelier_root)
    assert metered["overLimit"] is True

    # subscription.json is the file the statusline reads.
    persisted = json.loads((atelier_root / "subscription.json").read_text())
    assert persisted["warning"] is True
    assert "reached" in persisted["message"]

    # The existing statusline consumer surfaces the plan message (auth present,
    # so it does not short-circuit to the 'login' tip).
    status_text = _resolve_status_text(atelier_root)
    assert "Monthly limit reached" in status_text


def test_auth_status_enrichment_is_additive_and_live(atelier_root: Path) -> None:
    _seed_ledger(atelier_root, "s", est_cost=6.0, saved=2.0)
    pr.claim_anonymous_trial(atelier_root, monthly_limit_usd=5.0)
    status = pr.auth_status(atelier_root)
    sub = status["subscription"]
    # Original trial keys preserved...
    assert sub["status"] == "FREE" and sub["plan"] == "LOCAL"
    # ...and live meter fields added (monthlySavingsInUsd no longer hardcoded 0).
    assert sub["overLimit"] is True
    assert sub["monthlySavingsInUsd"] == pytest.approx(2.0)


def test_stop_event_refreshes_meter(atelier_root: Path) -> None:
    _seed_ledger(atelier_root, "s", est_cost=6.0, saved=2.0)
    pr.claim_anonymous_trial(atelier_root, monthly_limit_usd=5.0)
    # No subscription.json yet (claim writes only auth.json).
    assert not (atelier_root / "subscription.json").exists()
    pr.update_session_stats(atelier_root, {"hook_event_name": "Stop", "session_id": "s"})
    persisted = json.loads((atelier_root / "subscription.json").read_text())
    assert persisted["overLimit"] is True
