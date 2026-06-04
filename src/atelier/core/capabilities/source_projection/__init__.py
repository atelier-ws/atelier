"""Source projection capability helpers."""

from .compact import CompactProjectionResult, build_compact_projection
from .edit import ProjectionEditError, apply_compact_projection_edit, apply_compact_projection_edits
from .mapping import build_compact_mapping, resolve_projected_range, suggest_exact_reread_range
from .models import (
    ProjectionDelta,
    ProjectionMapping,
    ProjectionSegment,
    SourceProjection,
    SourceRange,
)

__all__ = [
    "CompactProjectionResult",
    "ProjectionDelta",
    "ProjectionEditError",
    "ProjectionMapping",
    "ProjectionSegment",
    "SourceProjection",
    "SourceRange",
    "apply_compact_projection_edit",
    "apply_compact_projection_edits",
    "build_compact_mapping",
    "build_compact_projection",
    "resolve_projected_range",
    "suggest_exact_reread_range",
]
