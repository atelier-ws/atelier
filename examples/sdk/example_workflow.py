"""SWE-agent + Atelier example workflow.

Demonstrates:
1. Prime reasoning context before tackling a GitHub issue
2. Rescue on tool failure
3. Record run trace after completion
4. Benchmark report

Run:
    cd atelier
    uv run python examples/sweagent/example_workflow.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from atelier.core.foundation.models import ReasonBlock
from atelier.gateway.adapters import SWEAgentAdapter, SWEAgentConfig
from atelier.gateway.sdk import AtelierClient


def _setup_store(client: AtelierClient) -> None:
    client.store.upsert_block(
        ReasonBlock(
            id="rb-test-isolation",
            title="Isolate test side effects",
            domain="Agent.swe",
            triggers=["test", "fixture", "mock"],
            situation="Fixing failing tests",
            dead_ends=["Modify production code to skip the test"],
            procedure=[
                "Use fixtures to isolate state",
                "Mock external dependencies",
                "Run tests in isolation first",
            ],
        )
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = str(Path(tmpdir) / ".atelier")

        client = AtelierClient.local(root=root)
        _setup_store(client)

        adapter = SWEAgentAdapter.from_config(
            SWEAgentConfig(
                mode="suggest",
                default_domain="Agent.swe",
                rescue_on_error=True,
                max_rescue_attempts=3,
            ),
            client=client,
        )

        # ── 1. Prime context ─────────────────────────────────────────────
        ctx = adapter.prime_context(
            task="Fix failing unit test: test_user_login asserts 200 but gets 403",
            files=["tests/test_auth.py", "auth/views.py"],
        )
        print(f"[context] {len(ctx.context)} chars of reasoning context")
        assert isinstance(ctx.context, str)

        # ── 2. Rescue on failure ─────────────────────────────────────────
        recovery = adapter.rescue_on_failure(
            task="Fix failing test",
            error="AssertionError: expected 200 got 403",
            recent_actions=["Read test file", "Modified views.py"],
            domain="Agent.swe",
        )
        print(f"[rescue] hint={recovery.rescue_result and recovery.rescue_result.rescue!r:.80}")

        # ── 3. Record run ────────────────────────────────────────────────
        adapter.record_run(
            task="Fix failing test: test_user_login",
            status="success",
            domain="Agent.swe",
            files_touched=["auth/views.py", "tests/test_auth.py"],
            commands_run=["pytest tests/test_auth.py -v"],
        )

        # ── 4. Benchmark report ──────────────────────────────────────────
        summary = adapter.benchmark_report()
        print(f"[savings] operations_tracked={summary.operations_tracked}")

    print("\nAll assertions passed ✓")


if __name__ == "__main__":
    main()
