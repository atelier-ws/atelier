"""Fuzzy matching helpers for atelier_edit (WP-24).

This module intentionally applies only to the batch-edit augmentation path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class FuzzyCandidate:
    start_line: int
    end_line: int
    start_offset: int
    end_offset: int
    distance: int
    ratio: float


class FuzzyAmbiguousMatchError(ValueError):
    """Raised when fuzzy matching finds multiple acceptable candidate ranges."""

    def __init__(self, candidates: list[FuzzyCandidate]) -> None:
        self.candidates = candidates
        ranges = ", ".join(f"{c.start_line}-{c.end_line}" for c in candidates)
        super().__init__(f"fuzzy replace ambiguous candidates at ranges: {ranges}")


_WS_RUN = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([:;,)\]\}])")


def normalize_for_fuzzy(text: str) -> str:
    """Normalize whitespace to tolerate indentation/trailing differences."""
    lines = text.splitlines()
    normalized_lines = []
    for line in lines:
        expanded = line.expandtabs(8).rstrip()
        collapsed = _WS_RUN.sub(" ", expanded).strip()
        normalized_lines.append(_SPACE_BEFORE_PUNCT.sub(r"\1", collapsed))
    return "\n".join(normalized_lines)


def bounded_levenshtein(a: str, b: str, max_distance: int) -> int | None:
    """Return edit distance if <= max_distance, else None.

    Uses a bounded DP to short-circuit expensive comparisons.
    """
    if max_distance < 0:
        return None
    if abs(len(a) - len(b)) > max_distance:
        return None
    if a == b:
        return 0

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        row_min = current[0]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + cost,
            )
            if current[j] < row_min:
                row_min = current[j]
        if row_min > max_distance:
            return None
        previous = current

    distance = previous[-1]
    return distance if distance <= max_distance else None


def find_fuzzy_candidates(
    content: str,
    old_string: str,
    *,
    distance_ratio: float = 0.05,
) -> list[FuzzyCandidate]:
    """Find candidate line windows that fuzzy-match old_string."""
    norm_old = normalize_for_fuzzy(old_string)
    if not norm_old:
        return []

    lines = content.splitlines(keepends=True)
    target_lines = max(1, len(old_string.splitlines()) or 1)
    if len(lines) < 1:
        return []

    # Permit small line-count drift caused by blank-line insertion/removal.
    line_lengths = {max(1, target_lines + delta) for delta in (-2, -1, 0, 1, 2)}
    line_lengths = {n for n in line_lengths if n <= len(lines)}
    if not line_lengths:
        return []

    max_distance = int(distance_ratio * max(1, len(norm_old)))
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    candidates: list[FuzzyCandidate] = []
    for window_len in sorted(line_lengths):
        max_start = len(lines) - window_len + 1
        for start_idx in range(max_start):
            end_idx = start_idx + window_len
            window = "".join(lines[start_idx:end_idx])
            norm_window = normalize_for_fuzzy(window)

            quick_ratio = SequenceMatcher(None, norm_old, norm_window, autojunk=False).ratio()
            if quick_ratio < 0.60:
                continue

            distance = bounded_levenshtein(norm_old, norm_window, max_distance)
            if distance is None:
                continue

            candidates.append(
                FuzzyCandidate(
                    start_line=start_idx + 1,
                    end_line=end_idx,
                    start_offset=offsets[start_idx],
                    end_offset=offsets[end_idx],
                    distance=distance,
                    ratio=quick_ratio,
                )
            )

    # Keep only the best-distance candidates.
    if not candidates:
        return []
    best_distance = min(c.distance for c in candidates)
    return [c for c in candidates if c.distance == best_distance]


def apply_fuzzy_replace(content: str, old_string: str, new_string: str) -> tuple[str, int, int]:
    """Apply fuzzy replacement for a line-window match.

    Returns (new_content, line_start, line_end).
    """
    candidates = find_fuzzy_candidates(content, old_string)
    if not candidates:
        raise ValueError("old_string not found in file")
    if len(candidates) > 1:
        raise FuzzyAmbiguousMatchError(candidates)

    c = candidates[0]
    replaced = content[: c.start_offset] + new_string + content[c.end_offset :]
    return replaced, c.start_line, c.end_line


__all__ = [
    "FuzzyAmbiguousMatchError",
    "FuzzyCandidate",
    "apply_fuzzy_replace",
    "bounded_levenshtein",
    "find_fuzzy_candidates",
    "normalize_for_fuzzy",
]
