"""Ablation: token_pin / two_tier / both on top of current HEAD (lexical only)."""

import json
import os
import pathlib
import subprocess

ENGINE = pathlib.Path("src/atelier/core/capabilities/code_context/engine.py")
FITNESS = "benchmarks/codebench/fitness_explore_mrr.py"

# ── exact strings that exist in current HEAD ─────────────────────────────────

ORIG_SORT = """        ranked_symbols = sorted(
            raw_symbols,
            key=lambda record: (
                0 if record.file_path in seed_set else 1,
                0 if record.symbol_id in exact_ids else 1,
                -(record.score or 0.0),
                record.file_path,
                record.start_line,
            ),
        )"""

ORIG_FILTER = """        # Path-quality filter FIRST: hard-remove minified/vendor artefacts and
        # soft-penalise test files BEFORE computing the score floor. This matters
        # because test files often score highest (function name appears many times
        # in test assertions), which would otherwise set a floor that eliminates
        # the actual implementation file. Pinned exact hits and seed files are exempt.
        query_wants_tests = bool(re.search(r"\\btest\\b|\\bspec\\b", query, re.IGNORECASE))
        if ranked_symbols:
            pinned_ids = exact_ids | anchor_ids
            pre_filtered: list[SymbolRecord] = []
            for record in ranked_symbols:
                fp = record.file_path or ""
                if _MINIFIED_FILE_RE.search(fp) or _VENDOR_PATH_RE.search(fp):
                    if record.symbol_id not in pinned_ids and fp not in seed_set:
                        continue  # hard remove before floor
                if not query_wants_tests and _TEST_PATH_RE.search(fp):
                    if record.symbol_id not in pinned_ids and fp not in seed_set:
                        record = record.model_copy(update={"score": (record.score or 0.0) * _TEST_SCORE_PENALTY})
                pre_filtered.append(record)
            ranked_symbols = pre_filtered
        # Relevance floor: when the top hit is strongly dominant (e.g. an exact
        # symbol scoring far above the lexical sub-token co-matches that share a
        # token like "get"/"name"), drop the near-zero tail so a precise query
        # returns the definition, not every file that merely shares a sub-token.
        # Pinned categories are always kept: the exact hit(s), the recall anchors
        # (zoekt/semantic, intentionally low/zero lexical score), and seed files --
        # so uniform low-score concept queries (floor ~ 0) keep everything.
        if ranked_symbols:
            top_score = max((record.score or 0.0) for record in ranked_symbols)
            floor = top_score * _EXPLORE_SCORE_FLOOR_FRAC
            if floor > 0:
                ranked_symbols = [
                    record
                    for record in ranked_symbols
                    if record.symbol_id in pinned_ids or record.file_path in seed_set or (record.score or 0.0) >= floor
                ]"""

# ── replacement pieces ────────────────────────────────────────────────────────

TOKEN_PIN_PREFIX = """        _query_words = frozenset(re.split(r"\\s+", query.strip()))
        token_exact_ids = {
            r.symbol_id for r in raw_symbols
            if r.symbol_name in _query_words or r.symbol_name.lower() in _query_words
        }
"""

SORT_WITH_TOKEN = """        ranked_symbols = sorted(
            raw_symbols,
            key=lambda record: (
                0 if record.file_path in seed_set else 1,
                0 if record.symbol_id in exact_ids or record.symbol_id in token_exact_ids else 1,
                -(record.score or 0.0),
                record.file_path,
                record.start_line,
            ),
        )"""

FILTER_WITH_TOKEN_PIN = ORIG_FILTER.replace(
    "            pinned_ids = exact_ids | anchor_ids",
    "            pinned_ids = exact_ids | anchor_ids | token_exact_ids",
)

TWO_TIER_FILTER = """        query_wants_tests = bool(re.search(r"\\btest\\b|\\bspec\\b", query, re.IGNORECASE))
        if ranked_symbols:
            definition_ids = exact_ids
            all_pinned = definition_ids | anchor_ids
            ranked_symbols = [
                r for r in ranked_symbols
                if r.symbol_id in all_pinned
                or r.file_path in seed_set
                or not (_MINIFIED_FILE_RE.search(r.file_path or "") or _VENDOR_PATH_RE.search(r.file_path or ""))
            ]
            if not query_wants_tests:
                non_test_scores = [
                    r.score or 0.0 for r in ranked_symbols
                    if r.symbol_id in definition_ids
                    or r.file_path in seed_set
                    or not _TEST_PATH_RE.search(r.file_path or "")
                ]
                top_score = max(non_test_scores) if non_test_scores else 0.0
                floor = top_score * _EXPLORE_SCORE_FLOOR_FRAC
                if floor > 0:
                    ranked_symbols = [
                        r for r in ranked_symbols
                        if r.symbol_id in all_pinned
                        or r.file_path in seed_set
                        or (r.score or 0.0) >= floor
                    ]
                impl_tier: list[SymbolRecord] = []
                test_tier: list[SymbolRecord] = []
                for r in ranked_symbols:
                    fp = r.file_path or ""
                    is_test = _TEST_PATH_RE.search(fp) and r.symbol_id not in definition_ids and r.file_path not in seed_set
                    if is_test:
                        test_tier.append(r.model_copy(update={"score": (r.score or 0.0) * _TEST_SCORE_PENALTY}))
                    else:
                        impl_tier.append(r)
                ranked_symbols = (
                    sorted(impl_tier, key=lambda r: -(r.score or 0.0))
                    + sorted(test_tier, key=lambda r: -(r.score or 0.0))
                )
            else:
                top_score = max((r.score or 0.0) for r in ranked_symbols) if ranked_symbols else 0.0
                floor = top_score * _EXPLORE_SCORE_FLOOR_FRAC
                if floor > 0:
                    ranked_symbols = [
                        r for r in ranked_symbols
                        if r.symbol_id in all_pinned
                        or r.file_path in seed_set
                        or (r.score or 0.0) >= floor
                    ]"""

TWO_TIER_WITH_TOKEN = TWO_TIER_FILTER.replace(
    "            definition_ids = exact_ids\n",
    "            definition_ids = exact_ids | token_exact_ids\n",
)


def patch(src: str, old: str, new: str) -> str:
    if old not in src:
        raise ValueError(f"patch target not found (first 80 chars): {old[:80]!r}")
    return src.replace(old, new, 1)


def restore():
    subprocess.run(["git", "checkout", str(ENGINE)], check=True, capture_output=True)


def run_fitness() -> dict | None:
    r = subprocess.run(
        ["uv", "run", "python", FITNESS],
        capture_output=True,
        text=True,
        env={**os.environ, "FITNESS_WORKERS": "4"},
    )
    lines = [ln for ln in r.stdout.strip().splitlines() if ln.startswith("{")]
    return json.loads(lines[-1]) if lines else None


orig = ENGINE.read_text()

CG_EXPLORE_MRR = 0.3415

tests = [
    ("baseline (current HEAD)", None),
    (
        "+ token_pin",
        lambda s: patch(patch(s, ORIG_SORT, TOKEN_PIN_PREFIX + SORT_WITH_TOKEN), ORIG_FILTER, FILTER_WITH_TOKEN_PIN),
    ),
    ("+ two_tier", lambda s: patch(s, ORIG_FILTER, TWO_TIER_FILTER)),
    (
        "+ token_pin + two_tier",
        lambda s: patch(patch(s, ORIG_SORT, TOKEN_PIN_PREFIX + SORT_WITH_TOKEN), ORIG_FILTER, TWO_TIER_WITH_TOKEN),
    ),
]

results = []
for name, fn in tests:
    print(f"\n=== {name} ===", flush=True)
    try:
        if fn is not None:
            ENGINE.write_text(fn(orig))
        r = run_fitness()
        if r:
            by = r.get("by_repo", {})
            beat = "BEATS CG" if r["mrr"] > CG_EXPLORE_MRR else f"behind by {CG_EXPLORE_MRR - r['mrr']:.4f}"
            print(f"  MRR={r['mrr']:.4f}  hit1={r['hit1']:.4f}  hit3={r['hit3']:.4f}  [{beat}]")
            for repo, v in sorted(by.items()):
                print(f"    {repo}: {v['mrr']:.4f}")
            results.append((name, r))
        else:
            print("  FAILED (no JSON output)")
    finally:
        if fn is not None:
            restore()

print("\n" + "=" * 65)
print(f"{'test':32} {'MRR':>8} {'hit@1':>8} {'hit@3':>8} {'vs CG':>10}")
print("-" * 65)
for name, r in results:
    delta = r["mrr"] - CG_EXPLORE_MRR
    sign = "+" if delta >= 0 else ""
    print(f"{name:32} {r['mrr']:8.4f} {r['hit1']:8.4f} {r['hit3']:8.4f} {sign}{delta:9.4f}")
print(f"{'CodeGraph cg_explore (ref)':32} {CG_EXPLORE_MRR:8.4f}")
