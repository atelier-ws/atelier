"""Fuzzy matching for the rich-edit path — backed by diff-match-patch."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from difflib import SequenceMatcher

from diff_match_patch import diff_match_patch as _DMP

# --------------------------------------------------------------------------- #
# Public data types (kept for backward compat)                                #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Text normalization helpers                                                   #
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Levenshtein (kept for callers / tests that import it directly)              #
# --------------------------------------------------------------------------- #


def bounded_levenshtein(a: str, b: str, max_distance: int) -> int | None:
    """Return edit distance if <= max_distance, else None."""
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


# --------------------------------------------------------------------------- #
# Core fuzzy replace — diff-match-patch backed                                #
# --------------------------------------------------------------------------- #

_DMP_THRESHOLD = 0.5

# Minimum similarity between the matched window and old_string before accepting a
# DMP-located replacement.  Values below this floor indicate a bad guess that
# would corrupt the file — we reject and surface a useful error instead.
_FUZZY_SIMILARITY_FLOOR = 0.90


def _make_dmp(content_len: int) -> _DMP:
    dmp = _DMP()
    dmp.Match_Threshold = _DMP_THRESHOLD
    dmp.Match_Distance = max(content_len, 1000)
    dmp.Match_MaxBits = 0  # no pattern-size limit (default 32 breaks long patterns)
    return dmp


def _find_exact_normalized_candidates(content: str, old_string: str) -> list[FuzzyCandidate]:
    lines = content.splitlines(keepends=True)
    offsets: list[int] = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    norm_old = normalize_for_fuzzy(old_string)
    n_old_lines = max(1, len(old_string.splitlines()))
    candidates: list[FuzzyCandidate] = []
    for start_line_idx in range(len(lines)):
        consumed = 0
        end_line_idx = start_line_idx
        while consumed < n_old_lines and end_line_idx < len(lines):
            if lines[end_line_idx].strip():
                consumed += 1
            end_line_idx += 1
        if consumed < n_old_lines:
            continue
        window = "".join(lines[start_line_idx:end_line_idx])
        if normalize_for_fuzzy(window) != norm_old:
            continue
        candidates.append(
            FuzzyCandidate(
                start_line=start_line_idx + 1,
                end_line=end_line_idx,
                start_offset=offsets[start_line_idx],
                end_offset=offsets[end_line_idx],
                distance=0,
                ratio=1.0,
            )
        )
    return candidates


def _anchor_end_line_idx(
    lines: list[str],
    start_idx: int,
    n_old_lines: int,
    old_string: str,
) -> int:
    """R3: locate the window end by finding the last non-blank line of old_string.

    More robust than "count N non-blank lines from DMP start": the window
    boundary is pinned to a concrete anchor, not a guess about blank-line drift.
    Falls back to the count-based approach when the anchor can't be located.
    """
    old_lines = old_string.splitlines()
    last_anchor_raw = next((line for line in reversed(old_lines) if line.strip()), None)
    if not last_anchor_raw:
        # All blank — use count-based
        pass
    else:
        norm_last = normalize_for_fuzzy(last_anchor_raw)
        search_end = min(start_idx + n_old_lines * 3 + 2, len(lines))
        for i in range(start_idx, search_end):
            if normalize_for_fuzzy(lines[i].rstrip("\n")) == norm_last:
                return i + 1  # exclusive end (line index after the last anchor)

    # Count-based fallback (original behaviour)
    consumed = 0
    end_idx = start_idx
    while consumed < n_old_lines and end_idx < len(lines):
        if lines[end_idx].strip():
            consumed += 1
        end_idx += 1
    return end_idx


def apply_fuzzy_replace(content: str, old_string: str, new_string: str) -> tuple[str, int, int]:
    """Fuzzy-replace old_string with new_string inside content.

    Matching ladder (strict → loose):
      R2  whitespace/typography-normalized exact, unique match
      R3  anchor match: DMP locates start; last non-blank line of old_string
          pins the window end (replaces fragile "count N lines" approach)
      R5  DMP location with similarity gate (≥ _FUZZY_SIMILARITY_FLOOR)

    Returns (new_content, 1-based line_start, 1-based line_end).
    Raises ValueError when no match meets the similarity floor.
    """
    lines = content.splitlines(keepends=True)
    offsets: list[int] = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    # R2: exact normalized, unique
    exact_candidates = _find_exact_normalized_candidates(content, old_string)
    if len(exact_candidates) == 1:
        candidate = exact_candidates[0]
        new_content = content[: candidate.start_offset] + new_string + content[candidate.end_offset :]
        return new_content, candidate.start_line, candidate.end_line

    # R3 / R5: DMP for start location, then anchor-based window + similarity gate
    dmp = _make_dmp(len(content))
    match_char = dmp.match_main(content, old_string, 0)
    if match_char == -1:
        raise ValueError("old_string not found in file")

    start_line_idx = max(0, bisect_right(offsets, match_char) - 1)
    n_old_lines = max(1, len(old_string.splitlines()))

    # R3: anchor-based window end (more precise than pure line-count)
    end_line_idx = _anchor_end_line_idx(lines, start_line_idx, n_old_lines, old_string)

    region_start = offsets[start_line_idx]
    region_end = offsets[end_line_idx]
    window_text = content[region_start:region_end]

    # Similarity gate: reject the rung if the matched window is too dissimilar.
    # This prevents silent corruption when DMP guesses a wrong location.
    norm_old = normalize_for_fuzzy(old_string)
    norm_window = normalize_for_fuzzy(window_text)
    similarity = SequenceMatcher(None, norm_old, norm_window, autojunk=False).ratio()
    if similarity < _FUZZY_SIMILARITY_FLOOR:
        raise ValueError(
            f"old_string not found in file "
            f"(best match similarity {similarity:.2f} < {_FUZZY_SIMILARITY_FLOOR:.2f}; "
            "re-read the file and supply exact disk content as old_string)"
        )

    new_content = content[:region_start] + new_string + content[region_end:]
    return new_content, start_line_idx + 1, end_line_idx


# --------------------------------------------------------------------------- #
# Legacy find_fuzzy_candidates (thin wrapper — retained for compat)           #
# --------------------------------------------------------------------------- #


def find_fuzzy_candidates(
    content: str,
    old_string: str,
    *,
    distance_ratio: float = 0.05,
) -> list[FuzzyCandidate]:
    """Find candidate line windows — now backed by DMP. Returns 0 or 1 result."""
    dmp = _make_dmp(len(content))
    match_char = dmp.match_main(content, old_string, 0)
    if match_char == -1:
        return []

    lines = content.splitlines(keepends=True)
    offsets: list[int] = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    start_line_idx = max(0, bisect_right(offsets, match_char) - 1)
    n_old_lines = max(1, len(old_string.splitlines()))
    end_line_idx = min(start_line_idx + n_old_lines, len(lines))

    norm_old = normalize_for_fuzzy(old_string)
    window = "".join(lines[start_line_idx:end_line_idx])
    norm_window = normalize_for_fuzzy(window)
    ratio = SequenceMatcher(None, norm_old, norm_window, autojunk=False).ratio()

    return [
        FuzzyCandidate(
            start_line=start_line_idx + 1,
            end_line=end_line_idx,
            start_offset=offsets[start_line_idx],
            end_offset=offsets[end_line_idx],
            distance=0,
            ratio=ratio,
        )
    ]


__all__ = [
    "_FUZZY_SIMILARITY_FLOOR",
    "FuzzyAmbiguousMatchError",
    "FuzzyCandidate",
    "_anchor_end_line_idx",
    "_find_exact_normalized_candidates",
    "apply_fuzzy_replace",
    "bounded_levenshtein",
    "find_fuzzy_candidates",
    "normalize_for_fuzzy",
]
