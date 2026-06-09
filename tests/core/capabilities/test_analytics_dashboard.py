"""Tests for the analytics web dashboard."""
from __future__ import annotations

import json


def test_serve_dashboard_imports() -> None:
    from atelier.core.capabilities.analytics.dashboard import serve_dashboard

    assert callable(serve_dashboard)


def test_html_template_is_non_empty_string() -> None:
    from atelier.core.capabilities.analytics.dashboard import HTML_TEMPLATE

    assert isinstance(HTML_TEMPLATE, str)
    assert HTML_TEMPLATE.strip()
    assert "Atelier Analytics" in HTML_TEMPLATE
    assert "/api/analytics" in HTML_TEMPLATE


def test_analytics_api_payload_is_valid_json(tmp_path) -> None:
    from atelier.core.capabilities.analytics.store import AnalyticsStore, SessionRecord

    store = AnalyticsStore(path=tmp_path / "analytics.db")
    store.upsert_session(
        SessionRecord(
            session_id="sess-test-123",
            started_at="2024-01-01T00:00:00",
            ended_at=None,
            model="anthropic/claude",
            provider="anthropic",
            mode="code",
            total_cost_usd=0.1234,
            total_savings_usd=0.5678,
            cache_efficiency_pct=72.5,
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=80,
            cache_write_tokens=20,
            turns=3,
            tool_calls=5,
        )
    )

    data = {
        "summary": store.summary_stats(),
        "sessions": [
            {
                "session_id": s.session_id,
                "model": s.model,
                "mode": s.mode,
                "cache_efficiency_pct": s.cache_efficiency_pct,
                "total_cost_usd": s.total_cost_usd,
                "total_savings_usd": s.total_savings_usd,
                "turns": s.turns,
                "started_at": s.started_at,
            }
            for s in store.recent_sessions(50)
        ],
    }
    store.close()

    body = json.dumps(data)
    reloaded = json.loads(body)
    assert reloaded["summary"]["total_sessions"] == 1
    assert reloaded["sessions"][0]["session_id"] == "sess-test-123"
    assert reloaded["sessions"][0]["mode"] == "code"
