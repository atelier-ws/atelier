"""Optimization Advisor capability.

The advisor is intentionally deterministic in v0: it uses captured Atelier
traces, policy presets, and conservative replay heuristics to explain likely
cost/quality trade-offs without silently changing runtime behavior.
"""

from atelier.core.capabilities.optimization.automation import (
    PROPOSAL_ARTIFACT_PATH,
    OptimizationProposalPrBot,
    run_optimization_cycle,
)
from atelier.core.capabilities.optimization.compaction_types import (
    ALL_COMPACTION_TYPES,
    CompactionType,
)
from atelier.core.capabilities.optimization.complexity import (
    ComplexityScore,
    ComplexitySignals,
    score_complexity,
    score_trace_complexity,
)
from atelier.core.capabilities.optimization.non_inferiority import (
    NonInferiorityVerdict,
    TerminalBenchArmSummary,
    evaluate_non_inferiority,
    evaluate_non_inferiority_from_runs,
    load_terminalbench_records,
    summarize_terminalbench_arm,
    wilson_interval,
)
from atelier.core.capabilities.optimization.optimizer import (
    Candidate,
    OptimizationResult,
    append_history,
    load_history,
    optimize_from_traces,
)
from atelier.core.capabilities.optimization.policy import (
    AutomationConfig,
    BenchmarkEvidence,
    CompactionPolicy,
    Policy,
    RoutingPolicy,
    load_automation_config,
    load_current_policy,
    preset_policy,
    save_automation_config,
    save_policy,
)

__all__ = [
    "ALL_COMPACTION_TYPES",
    "PROPOSAL_ARTIFACT_PATH",
    "AutomationConfig",
    "BenchmarkEvidence",
    "Candidate",
    "CompactionPolicy",
    "CompactionType",
    "ComplexityScore",
    "ComplexitySignals",
    "NonInferiorityVerdict",
    "OptimizationProposalPrBot",
    "OptimizationResult",
    "Policy",
    "RoutingPolicy",
    "TerminalBenchArmSummary",
    "append_history",
    "evaluate_non_inferiority",
    "evaluate_non_inferiority_from_runs",
    "load_automation_config",
    "load_current_policy",
    "load_history",
    "load_terminalbench_records",
    "optimize_from_traces",
    "preset_policy",
    "run_optimization_cycle",
    "save_automation_config",
    "save_policy",
    "score_complexity",
    "score_trace_complexity",
    "summarize_terminalbench_arm",
    "wilson_interval",
]
