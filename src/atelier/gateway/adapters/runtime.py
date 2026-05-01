"""In-process runtime adapter — used by Beseam product agents.

Usage:

    from atelier.gateway.adapters.runtime import ReasoningRuntime

    rt = ReasoningRuntime(root=".atelier")
    with rt.run(domain="beseam.shopify.publish", task=task,
                tools=["shopify.update_metafield"]) as session:
        session.inject_reasoning_context()
        plan = agent.plan()
        session.check_plan(plan)
        result = agent.execute(monitors=session.monitors)
        session.verify(result, rubric_id="rubric_shopify_publish")
        session.record_trace(result)
        session.extract_candidate_blocks()
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atelier.core.foundation.extractor import CandidateBlock, extract_candidate
from atelier.core.foundation.models import (
    PlanCheckResult,
    ReasonBlock,
    RescueResult,
    RubricResult,
    ToolCall,
    Trace,
    ValidationResult,
)
from atelier.core.foundation.monitors import (
    MonitorAlert,
    SessionState,
    args_signature,
    default_monitors,
    error_signature,
    run_monitors,
)
from atelier.core.foundation.plan_checker import check_plan
from atelier.core.foundation.renderer import render_context_for_agent
from atelier.core.foundation.retriever import ScoredBlock, TaskContext, retrieve, score_block
from atelier.core.foundation.rubric_gate import run_rubric
from atelier.core.foundation.store import ReasoningStore
from atelier.core.runtime import AtelierRuntimeCore


def _load_domain_reasonblocks(store_root: Path) -> list[ReasonBlock]:
    from atelier.core.domains import DomainManager

    manager = DomainManager(store_root)
    blocks: list[ReasonBlock] = []
    seen_ids: set[str] = set()

    for block in manager.all_reasonblocks():
        if block.id in seen_ids or block.status in ("quarantined",):
            continue
        seen_ids.add(block.id)
        blocks.append(block)

    return blocks


def _retrieve_with_pack_context(
    store: ReasoningStore,
    ctx: TaskContext,
    *,
    limit: int,
) -> list[ScoredBlock]:
    # Retrieve learned/runtime blocks first, then merge with domain bundle blocks.
    learned = retrieve(store, ctx, limit=max(limit * 3, 15))
    merged: dict[str, ScoredBlock] = {entry.block.id: entry for entry in learned}

    for block in _load_domain_reasonblocks(store.root):
        if block.status == "deprecated":
            continue
        scored = score_block(block, ctx)
        if scored.score < 0.15:
            continue
        existing = merged.get(block.id)
        if existing is None or scored.score > existing.score:
            merged[block.id] = scored

    ranked = sorted(merged.values(), key=lambda entry: entry.score, reverse=True)
    return ranked[:limit]


@dataclass
class RuntimeSession:
    """A single agent run wrapped by the reasoning runtime."""

    domain: str
    task: str
    agent: str
    files: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    state: SessionState = field(default_factory=SessionState)
    store: ReasoningStore | None = None
    trace_id: str | None = None
    monitors: list[Any] = field(default_factory=default_monitors)
    core_runtime: AtelierRuntimeCore | None = None

    # ----- context injection ---------------------------------------------- #

    def inject_reasoning_context(self, *, max_blocks: int = 5) -> str:
        if self.core_runtime is not None:
            return self.core_runtime.get_reasoning_context(
                task=self.task,
                domain=self.domain,
                files=self.files,
                tools=self.tools,
                max_blocks=max_blocks,
            )
        assert self.store is not None
        ctx = TaskContext(task=self.task, domain=self.domain, files=self.files, tools=self.tools)
        scored = _retrieve_with_pack_context(self.store, ctx, limit=max_blocks)
        return render_context_for_agent([s.block for s in scored])

    # ----- plan checking --------------------------------------------------- #

    def check_plan(self, plan: list[str]) -> PlanCheckResult:
        assert self.store is not None
        self.state.plan = plan
        return check_plan(
            self.store,
            task=self.task,
            plan=plan,
            domain=self.domain,
            files=self.files,
            tools=self.tools,
        )

    # ----- monitor hooks --------------------------------------------------- #

    def record_command(self, command: str, *, succeeded: bool, error: str = "") -> None:
        sig = error_signature(error) if error else ""
        self.state.commands_run.append(command)
        self.state.command_results.append((command, succeeded, sig))

    def record_tool_call(self, name: str, args: dict[str, Any] | None = None) -> None:
        self.state.tool_calls.append((name, args_signature(args)))

    def record_tool_output(self, output: str) -> None:
        self.state.tool_outputs_chars += len(output)

    def run_monitors(self) -> list[MonitorAlert]:
        assert self.store is not None
        ctx = TaskContext(task=self.task, domain=self.domain, files=self.files, tools=self.tools)
        blocks = [s.block for s in _retrieve_with_pack_context(self.store, ctx, limit=10)]
        return run_monitors(self.state, blocks, self.monitors)

    # ----- rubric gate ----------------------------------------------------- #

    def verify(self, checks: dict[str, bool | None], rubric_id: str) -> RubricResult:
        assert self.store is not None
        rubric = self.store.get_rubric(rubric_id)
        if rubric is None:
            raise KeyError(f"rubric not found: {rubric_id}")
        result = run_rubric(rubric, checks)
        self.state.rubric_run = True
        self.state.validation_passed = result.status != "blocked"
        return result

    # ----- trace recording ------------------------------------------------- #

    def record_trace(
        self,
        *,
        status: str,
        diff_summary: str = "",
        output_summary: str = "",
        validation_results: list[ValidationResult] | None = None,
    ) -> Trace:
        assert self.store is not None
        from atelier.core.foundation.redaction import redact, redact_list

        trace = Trace(
            id=Trace.make_id(self.task, self.agent),
            agent=self.agent,
            domain=self.domain,
            task=redact(self.task),
            status=status,  # type: ignore[arg-type]
            files_touched=list(self.files),
            tools_called=[
                ToolCall(name=name, args_hash=sig, count=1) for name, sig in self.state.tool_calls
            ],
            commands_run=redact_list(self.state.commands_run),
            errors_seen=redact_list(
                [sig for _, ok, sig in self.state.command_results if not ok and sig]
            ),
            diff_summary=redact(diff_summary),
            output_summary=redact(output_summary),
            validation_results=validation_results or [],
        )
        self.store.record_trace(trace)
        self.trace_id = trace.id
        return trace

    # ----- candidate extraction ------------------------------------------- #

    def extract_candidate_blocks(self) -> CandidateBlock | None:
        assert self.store is not None
        if not self.trace_id:
            return None
        trace = self.store.get_trace(self.trace_id)
        if trace is None:
            return None
        return extract_candidate(trace)


# --------------------------------------------------------------------------- #
# Runtime façade                                                              #
# --------------------------------------------------------------------------- #


class ReasoningRuntime:
    """Top-level facade for product agents."""

    def __init__(self, root: str | Path = ".atelier") -> None:
        self.core_runtime = AtelierRuntimeCore(root)
        self.store = self.core_runtime.store

    @contextmanager
    def run(
        self,
        *,
        domain: str,
        task: str,
        agent: str = "beseam-product-agent",
        files: list[str] | None = None,
        tools: list[str] | None = None,
    ) -> Iterator[RuntimeSession]:
        session = RuntimeSession(
            domain=domain,
            task=task,
            agent=agent,
            files=files or [],
            tools=tools or [],
            store=self.store,
            core_runtime=self.core_runtime,
        )
        try:
            yield session
        finally:
            # Make sure something is recorded even if the agent crashed.
            if session.trace_id is None:
                with suppress(Exception):  # pragma: no cover - defensive
                    session.record_trace(status="partial")

    # ----- standalone helpers used by MCP/CLI ----------------------------- #

    def get_reasoning_context(
        self,
        *,
        task: str,
        domain: str | None = None,
        files: list[str] | None = None,
        tools: list[str] | None = None,
        errors: list[str] | None = None,
        max_blocks: int = 5,
    ) -> str:
        return self.core_runtime.get_reasoning_context(
            task=task,
            domain=domain,
            files=files,
            tools=tools,
            errors=errors,
            max_blocks=max_blocks,
        )

    def rescue_failure(
        self,
        *,
        task: str,
        error: str,
        files: list[str] | None = None,
        recent_actions: list[str] | None = None,
        domain: str | None = None,
    ) -> RescueResult:
        scored = self.core_runtime.reasoning_reuse.retrieve(
            task=task,
            domain=domain,
            files=files,
            errors=[error],
            limit=3,
        )
        if not scored:
            return RescueResult(
                rescue=(
                    "No matching ReasonBlock found. Stop and summarize: "
                    "files changed, errors seen, assumptions tested, current "
                    "blocker. Then ask for guidance."
                ),
                matched_blocks=[],
            )
        top = scored[0].block
        rescue = f"Stop retrying. Apply procedure '{top.title}': " + " | ".join(top.procedure)
        if top.verification:
            rescue += " | Verify: " + ", ".join(top.verification)
        return RescueResult(
            rescue=rescue,
            matched_blocks=[s.block.id for s in scored],
        )
