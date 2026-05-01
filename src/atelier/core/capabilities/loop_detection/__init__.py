"""Loop detection capability — public API."""

from .capability import LoopDetectionCapability
from .models import LoopReport, PatternMatch, TrajectoryPoint
from .rescue import _RESCUE_MAP, match_rescue
from .signatures import _loop_signature, hamming_distance, near_duplicate_errors

__all__ = [
    "_RESCUE_MAP",
    "LoopDetectionCapability",
    "LoopReport",
    "PatternMatch",
    "TrajectoryPoint",
    "_loop_signature",
    "hamming_distance",
    "match_rescue",
    "near_duplicate_errors",
]
