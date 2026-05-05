"""Token budget fitting for repo maps."""

from __future__ import annotations

from collections.abc import Callable

import tiktoken

_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def fit_to_budget(
    ranked_files: list[str], render: Callable[[list[str]], str], budget_tokens: int
) -> tuple[list[str], str]:
    lo = 0
    hi = len(ranked_files)
    best_files: list[str] = []
    best_text = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        current_files = ranked_files[:mid]
        text = str(render(current_files))
        if count_tokens(text) <= budget_tokens:
            best_files = current_files
            best_text = text
            lo = mid + 1
        else:
            hi = mid - 1
    if not best_files and ranked_files:
        best_files = ranked_files[:1]
        best_text = str(render(best_files))
    return best_files, best_text


__all__ = ["count_tokens", "fit_to_budget"]
