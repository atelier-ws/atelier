"""Loop signatures and SimHash-based near-duplicate detection."""

from __future__ import annotations

import hashlib
import re

# ---------------------------------------------------------------------------
# Stable loop signature (SHA-1 based) — backward-compatible
# ---------------------------------------------------------------------------


def _loop_signature(parts: list[str]) -> str:
    """Return a 12-char hex SHA-1 of the joined parts list (stable across runs)."""
    joined = "|".join(parts)
    return hashlib.sha1(joined.encode(), usedforsecurity=False).hexdigest()[:12]


# ---------------------------------------------------------------------------
# SimHash — 64-bit locality-sensitive hash for near-duplicate detection
# ---------------------------------------------------------------------------


def _simhash(text: str) -> int:
    """Compute a 64-bit SimHash of *text* for near-duplicate detection."""
    tokens = re.findall(r"[\w']+", text.lower())
    if not tokens:
        return 0
    bit_vector = [0] * 64
    for token in tokens:
        h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
        for i in range(64):
            if h & (1 << i):
                bit_vector[i] += 1
            else:
                bit_vector[i] -= 1
    result = 0
    for i in range(64):
        if bit_vector[i] > 0:
            result |= 1 << i
    return result


def hamming_distance(a: int, b: int) -> int:
    """Count differing bits between two SimHash values."""
    return bin(a ^ b).count("1")


def near_duplicate_errors(errors: list[str], *, threshold: int = 8) -> list[list[str]]:
    """
    Group error messages that are near-duplicates (hamming distance ≤ threshold).

    Returns a list of groups; each group is a list of similar error strings.
    """
    if not errors:
        return []
    hashes = [_simhash(e) for e in errors]
    used: set[int] = set()
    groups: list[list[str]] = []
    for i, (h_i, e_i) in enumerate(zip(hashes, errors, strict=False)):
        if i in used:
            continue
        group = [e_i]
        used.add(i)
        for j in range(i + 1, len(errors)):
            if j not in used and hamming_distance(h_i, hashes[j]) <= threshold:
                group.append(errors[j])
                used.add(j)
        groups.append(group)
    return groups
