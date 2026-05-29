"""Retry budget tracker for the verification loop (M3)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetryBudget:
    """Caps verification retries per subtask (default 3, per the M3 plan)."""

    max_attempts: int = 3
    used: int = 0

    def consume(self) -> None:
        self.used += 1

    def exhausted(self) -> bool:
        return self.used >= self.max_attempts

    def remaining(self) -> int:
        return max(0, self.max_attempts - self.used)
