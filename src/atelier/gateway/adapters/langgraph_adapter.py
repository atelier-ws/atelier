"""LangGraph middleware adapter for Atelier.

Wrap the stable AtelierClient SDK so LangGraph graphs can call Atelier
programmatically at node boundaries:
- ``node_pre_check``       - reasoning-block gate before a node runs
- ``edge_rubric_gate``     - rubric gate on a conditional edge
- ``node_failure_recovery``- failure analysis when a node raises

Usage::

    from langgraph.graph import StateGraph
    from atelier.gateway.adapters import LangGraphAdapter, LangGraphConfig
    from atelier.gateway.sdk import AtelierClient

    client = AtelierClient.local()
    atelier = LangGraphAdapter.from_config(
        LangGraphConfig(
            mode="suggest",
            node_domain_map={"plan_node": "Agent.codegen"},
        ),
        client=client,
    )

    def plan_node(state):
        decision = atelier.node_pre_check("plan_node", task=state["task"], plan=state["plan"])
        if decision.blocked:
            return {"error": decision.warnings}
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from atelier.gateway.adapters.adapter_base import AdapterDecision, AdapterMode, AgentAdapter
from atelier.gateway.sdk import AtelierClient
from atelier.gateway.sdk.client import FailureAnalysisResult, SavingsSummary


class LangGraphConfig(BaseModel):
    """Configuration for the LangGraph adapter."""

    model_config = ConfigDict(extra="forbid")

    mode: AdapterMode = "shadow"
    default_domain: str | None = None
    default_tools: list[str] = []
    node_domain_map: dict[str, str] = {}


@dataclass
class LangGraphAdapter(AgentAdapter):
    """Atelier adapter for LangGraph.

    Allows LangGraph nodes and edges to call Atelier at runtime:
    - ``node_pre_check``        - pre-plan gate at a node boundary
    - ``edge_rubric_gate``      - rubric check on a conditional edge
    - ``node_failure_recovery`` - failure analysis when a node raises
    - ``graph_savings``         - cost-savings summary for a completed graph run
    - ``graph_failure_clusters``- cluster repeated failures across a graph run
    """

    host: str = "langgraph"
    node_domain_map: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: LangGraphConfig, *, client: AtelierClient) -> LangGraphAdapter:
        """Create an adapter from a ``LangGraphConfig``."""
        return cls(
            client=client,
            mode=config.mode,
            host="langgraph",
            default_domain=config.default_domain,
            default_tools=list(config.default_tools),
            node_domain_map=dict(config.node_domain_map),
        )

    def _domain_for(self, node_name: str) -> str | None:
        """Return the domain for a node, falling back to ``default_domain``."""
        return self.node_domain_map.get(node_name) or self.default_domain

    def node_pre_check(
        self,
        node_name: str,
        *,
        task: str,
        plan: list[str],
        files: list[str] | None = None,
        tools: list[str] | None = None,
    ) -> AdapterDecision:
        """Run a pre-plan reasoning check at a LangGraph node boundary.

        The domain is resolved from ``node_domain_map[node_name]`` if present,
        falling back to ``default_domain``.
        """
        return self.pre_plan_check(
            task=task,
            plan=plan,
            domain=self._domain_for(node_name),
            files=files,
            tools=tools,
        )

    def edge_rubric_gate(
        self,
        node_name: str,
        *,
        rubric_id: str,
        checks: dict[str, bool | None],
    ) -> AdapterDecision:
        """Run a rubric gate on a LangGraph conditional edge."""
        return self.verify_rubric(rubric_id=rubric_id, checks=checks)

    def node_failure_recovery(
        self,
        node_name: str,
        *,
        task: str,
        error: str,
        files: list[str] | None = None,
        recent_actions: list[str] | None = None,
    ) -> AdapterDecision:
        """Analyse a node failure and return a recovery hint."""
        return self.analyze_failure(
            task=task,
            error=error,
            domain=self._domain_for(node_name),
            files=files,
            recent_actions=recent_actions,
        )

    def graph_savings(self) -> SavingsSummary:
        """Return cost-savings summary for the current graph run."""
        return self.benchmark_report()

    def graph_failure_clusters(
        self, *, node_name: str | None = None, limit: int = 100
    ) -> FailureAnalysisResult:
        """Cluster repeated failures across a graph run."""
        domain = self._domain_for(node_name) if node_name else self.default_domain
        return self.failure_clusters(domain=domain, limit=limit)

    @classmethod
    def install(cls) -> str:
        """Return installation instructions for LangGraph integration."""
        return (
            "# LangGraph ← Atelier integration\n"
            "1. pip install atelier-runtime\n"
            "2. atelier init\n"
            "3. Instantiate LangGraphAdapter in your graph builder:\n"
            "   atelier = LangGraphAdapter(client=AtelierClient.local(), mode='suggest')\n"
            "   # In each node function:\n"
            "   decision = atelier.node_pre_check(node_name, task=task, plan=plan)\n"
            "   if decision.blocked: raise ValueError(decision.warnings)\n"
            "See docs/integrations/langgraph.md for full reference."
        )
