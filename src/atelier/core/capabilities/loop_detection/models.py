"""Data models for loop detection capability."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PatternMatch:
    """Single detected pattern within a trajectory."""

    pattern_name: str  # e.g. 'patch_revert_cycle', 'search_read_loop'
    severity: str  # 'low' | 'medium' | 'high'
    evidence: list[str] = field(default_factory=list)
    count: int = 0


@dataclass
class TrajectoryPoint:
    """Single step in an agent's execution trajectory."""

    turn: int
    kind: str  # event kind
    summary: str
    signature: str = ""  # SimHash-based near-duplicate key


@dataclass
class LoopReport:
    """Full loop detection analysis result."""

    loop_detected: bool
    severity: str  # 'none' | 'low' | 'medium' | 'high'
    loop_types: list[str]  # names of detected patterns
    prior_attempts: int
    rescue_strategies: list[str]
    patterns: list[PatternMatch] = field(default_factory=list)
    cascade_chain: list[str] = field(default_factory=list)  # error chain
    budget_risk: bool = False  # True when budget nearly exhausted
    risk_score: float = 0.0  # Composite loop risk in [0, 1]
    wasted_tokens: int = 0  # Estimated tokens wasted by detected loops
    # Phase 3 additions
    risk_velocity: float = 0.0  # Rate of risk growth (positive = accelerating)
    rescue_scores: dict[str, float] = field(default_factory=dict)  # strategy -> confidence [0,1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "loop_detected": self.loop_detected,
            "severity": self.severity,
            "loop_types": self.loop_types,
            "prior_attempts": self.prior_attempts,
            "rescue_strategies": self.rescue_strategies,
            "cascade_chain": self.cascade_chain,
            "budget_risk": self.budget_risk,
            "risk_score": self.risk_score,
            "wasted_tokens": self.wasted_tokens,
            "risk_velocity": self.risk_velocity,
            "rescue_scores": self.rescue_scores,
        }
