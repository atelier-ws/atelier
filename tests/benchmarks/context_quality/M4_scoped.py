"""M4 — Scoped pull-context benchmark: retrieval precision + recall.

Measures whether :class:`ScopedContextCapability` retrieves the *right* scope
for a multi-file subtask and keeps noise out of the top results. Runs against a
real ``CodeContextEngine`` index built over a controlled multi-domain fixture
repo (4 domains x 3 files + cross-domain distractors), so the metric reflects
ranking/scoping quality deterministically. A real-repo variant labelled from
commit history is future work.

Targets (README): precision >=0.6, recall >=0.85.
  * recall          = fraction of a subtask's relevant files retrieved.
  * precision@k      = top-k purity at k=|relevant|+1 (exposes one noise slot).

Run explicitly (slow):
    uv run pytest tests/benchmarks/context_quality/M4_scoped.py -v -m slow
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from statistics import mean

import pytest

from atelier.core.capabilities.code_context import CodeContextEngine
from atelier.core.capabilities.scoped_context import ScopedContextCapability, Subtask

# domain -> {module_stem: keyword-rich body}
_DOMAINS: dict[str, dict[str, str]] = {
    "auth": {
        "auth_login": "login authenticate credentials password user",
        "auth_session": "session login user lifecycle cookie",
        "auth_tokens": "auth token jwt issue verify user",
    },
    "payments": {
        "pay_charge": "charge credit card payment amount",
        "pay_refund": "refund payment reverse charge",
        "pay_audit": "audit log payment charge refund trail",
    },
    "search": {
        "srch_bm25": "bm25 lexical relevance scoring rank",
        "srch_rank": "rank results scoring search order",
        "srch_index": "index documents search tokens postings",
    },
    "cache": {
        "cache_prefix": "prefix cache key stable hash",
        "cache_planner": "cache planner breakpoint plan reuse",
        "cache_evict": "cache eviction ttl expire evict",
    },
}

# (subtask description, target domain) — each targets one domain's 3 files.
_QUERIES: list[tuple[str, str]] = [
    ("authenticate user login session token", "auth"),
    ("charge refund credit card payment audit", "payments"),
    ("bm25 ranking over the search index documents", "search"),
    ("prefix cache planner breakpoint eviction", "cache"),
]


def _build_fixture(root: Path) -> None:
    for files in _DOMAINS.values():
        for stem, kw in files.items():
            (root / f"{stem}.py").write_text(
                f'def {stem}(x):\n    """{kw} {kw}"""\n    return x  # {kw}\n',
                encoding="utf-8",
            )
    subprocess.run(["git", "init", "-q"], cwd=root, check=False)
    subprocess.run(["git", "add", "-A"], cwd=root, check=False)


@pytest.mark.slow
def test_m4_precision_recall(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    cap = ScopedContextCapability(CodeContextEngine(tmp_path))

    precisions: list[float] = []
    recalls: list[float] = []
    for query, domain in _QUERIES:
        relevant = set(_DOMAINS[domain])
        k = len(relevant) + 1  # one slot beyond the relevant set exposes noise
        scoped = cap.pull(Subtask(description=query, budget_tokens=3000))
        ordered: list[str] = []
        for chunk in scoped.chunks:
            stem = Path(chunk.path).stem
            if stem not in ordered:
                ordered.append(stem)
        retrieved = set(ordered)
        top_k = ordered[:k]
        precision = len(set(top_k) & relevant) / len(top_k) if top_k else 0.0
        recall = len(retrieved & relevant) / len(relevant)
        precisions.append(precision)
        recalls.append(recall)

    mean_precision = mean(precisions)
    mean_recall = mean(recalls)

    assert mean_precision >= 0.6, f"precision {mean_precision:.2f} below 0.60 target"
    assert mean_recall >= 0.85, f"recall {mean_recall:.2f} below 0.85 target"
