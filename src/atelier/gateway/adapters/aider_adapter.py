"""Aider middleware adapter for Atelier.

Wrap the stable AtelierClient SDK so Aider can:
- Validate an edit plan against reasoning blocks before applying changes
- Gate a session with a rubric check
- Expose cost-savings benchmark data from the embedded tracker

Usage::

    from atelier.gateway.adapters import AiderAdapter, AiderConfig
    from atelier.gateway.sdk import AtelierClient

    client = AtelierClient.local()
    adapter = AiderAdapter.from_config(AiderConfig(mode="suggest"), client=client)

    decision = adapter.validate_plan(
        task="Add OAuth to checkout",
        plan=["Modify views.py", "Add /oauth/callback route"],
    )
    savings = adapter.get_savings()
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from atelier.gateway.adapters.adapter_base import AdapterDecision, AdapterMode, AgentAdapter
from atelier.gateway.sdk import AtelierClient
from atelier.gateway.sdk.client import SavingsSummary


class AiderConfig(BaseModel):
    """Configuration for the Aider adapter."""

    model_config = ConfigDict(extra="forbid")

    mode: AdapterMode = "shadow"
    default_domain: str | None = None
    default_rubric_id: str | None = None
    default_tools: list[str] = []
    track_savings: bool = True


@dataclass
class AiderAdapter(AgentAdapter):
    """Atelier adapter for Aider.

    Provides:
    - ``validate_plan``  - pre-plan reasoning check before Aider runs edits
    - ``rubric_gate``    - rubric check after Aider generates a diff
    - ``get_savings``    - cost-savings summary from the embedded tracker
    """

    host: str = "aider"
    default_rubric_id: str | None = None
    track_savings: bool = True

    @classmethod
    def from_config(cls, config: AiderConfig, *, client: AtelierClient) -> AiderAdapter:
        """Create an adapter from an ``AiderConfig``."""
        return cls(
            client=client,
            mode=config.mode,
            host="aider",
            default_domain=config.default_domain,
            default_tools=list(config.default_tools),
            default_rubric_id=config.default_rubric_id,
            track_savings=config.track_savings,
        )

    def validate_plan(
        self,
        *,
        task: str,
        plan: list[str],
        domain: str | None = None,
        files: list[str] | None = None,
    ) -> AdapterDecision:
        """Check an Aider edit plan against loaded reasoning blocks.

        shadow  - observe only; never blocks the edit.
        suggest - surface warnings but allow Aider to proceed.
        enforce - block if any dead-end pattern is matched.
        """
        return self.pre_plan_check(task=task, plan=plan, domain=domain, files=files)

    def rubric_gate(
        self,
        *,
        rubric_id: str | None = None,
        checks: dict[str, bool | None] | None = None,
    ) -> AdapterDecision | None:
        """Run a rubric gate if rubric_id and checks are available."""
        rid = rubric_id or self.default_rubric_id
        if not rid or checks is None:
            return None
        return self.verify_rubric(rubric_id=rid, checks=checks)

    def get_savings(self) -> SavingsSummary:
        """Return cost-savings summary from the embedded tracker."""
        return self.benchmark_report()

    @classmethod
    def install(cls) -> str:
        """Return installation instructions for Aider integration."""
        return (
            "# Aider ← Atelier integration\n"
            "1. pip install atelier-runtime\n"
            "2. atelier init\n"
            "3. In your Aider pre-edit hook or wrapper:\n"
            "   adapter = AiderAdapter(client=AtelierClient.local(), mode='suggest')\n"
            "   decision = adapter.validate_plan(task=task, plan=planned_edits)\n"
            "   if decision.blocked: sys.exit(1)\n"
            "See docs/integrations/aider.md for full reference."
        )
