"""Convert build_real_retrieval_corpus.py JSONL → bench_pairs JSON.

Reads the JSONL produced by experiments/retrieval_symbol_vote/build_real_retrieval_corpus.py
(which mines agent grep patterns + problem statements from SWE-bench flow dumps
and uses the patch files as gold), and emits the bench_pairs format consumed by
``atelier eval retrieval --pairs <file>``.

Usage::

    # Mine from SWE-bench flows (both runs for more coverage):
    uv run python experiments/retrieval_symbol_vote/build_real_retrieval_corpus.py \\
        --dump-root reports/benchmark/codebench/swe50_final_5rep \\
        --dump-root reports/benchmark/codebench/swe50_stress_run1 \\
        --allow-no-exclusions \\
        --include-problem-statements \\
        --output /tmp/swe_corpus.jsonl

    # Convert:
    uv run python benchmarks/codebench/convert_swe_corpus.py \\
        --in /tmp/swe_corpus.jsonl \\
        --out benchmarks/codebench/data/bench_pairs_swebench_gold.json

    # Eval:
    atelier eval retrieval --pairs benchmarks/codebench/data/bench_pairs_swebench_gold.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

_MIN_PER_REPO = 100  # augment with synthetic pairs when real count falls below this

# Which query_source types to include by default.
# agent_grep  → actual search patterns used during task (multi-keyword, real intent)
# problem_statement → natural-language bug description (richest, hardest queries)
# agent_read  -> file paths being opened, NOT useful as search queries -- excluded
_DEFAULT_SOURCES = {"agent_grep", "problem_statement"}

# Cap problem statements at this many chars so they do not overwhelm indexers.
_PS_MAX_CHARS = 400


def _tid(task_id: str, query: str) -> str:
    """Stable unique ID for a (task, query) pair."""
    key = f"{task_id}\x00{query}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert SWE corpus JSONL → bench_pairs JSON")
    parser.add_argument("--in", dest="inp", required=True, help="JSONL from build_real_retrieval_corpus.py")
    parser.add_argument("--out", required=True, help="Output bench_pairs JSON path")
    parser.add_argument(
        "--meta",
        default="benchmarks/codebench/data/bench_pairs_def_gold.json",
        help="Existing bench_pairs JSON with repo workspace metadata",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        default=sorted(_DEFAULT_SOURCES),
        help="query_source types to include (default: agent_grep problem_statement)",
    )
    parser.add_argument(
        "--max-ps-chars",
        type=int,
        default=_PS_MAX_CHARS,
        help="Truncate problem_statement queries to this many chars",
    )
    parser.add_argument(
        "--min-per-repo",
        type=int,
        default=_MIN_PER_REPO,
        help="Augment repos below this count with synthetic pairs (0 = disable)",
    )
    parser.add_argument(
        "--extra-pairs",
        nargs="+",
        default=[],
        metavar="FILE",
        help="Additional bench_pairs JSON files to merge in (e.g. session-mined pairs for atelier)",
    )
    args = parser.parse_args()

    # Load workspace metadata from existing bench gold.
    meta_path = Path(args.meta)
    known_repos: dict[str, dict] = {}
    if meta_path.exists():
        known_repos = json.loads(meta_path.read_text()).get("repos", {})
    else:
        print(f"[warn] --meta {meta_path} not found; all repos will be skipped", file=sys.stderr)

    sources = set(args.sources)
    pairs: list[list] = []  # [[query, tid, repo_prefix], ...]
    true_map: dict[str, list] = {}  # tid -> [gold_files]
    repos: dict[str, dict] = {}  # repo_prefix -> ws metadata

    seen_pairs: set[tuple] = set()
    skipped_no_gold = 0
    skipped_no_ws: dict[str, int] = defaultdict(int)
    counts_by_source: dict[str, int] = defaultdict(int)

    for raw in Path(args.inp).read_text().splitlines():
        raw = raw.strip()
        if not raw:
            continue
        rec = json.loads(raw)

        source = rec.get("query_source", "")
        if source not in sources:
            continue

        repo_prefix = rec["repo_prefix"]
        gold_files: list[str] = rec.get("gold_files") or []
        if not gold_files:
            skipped_no_gold += 1
            continue

        ws_meta = known_repos.get(repo_prefix)
        if ws_meta is None:
            skipped_no_ws[repo_prefix] += 1
            continue

        query: str = rec["query"].strip()
        if source == "problem_statement" and len(query) > args.max_ps_chars:
            query = query[: args.max_ps_chars].rsplit(" ", 1)[0] + "…"

        tid = _tid(rec["task_id"], rec["query"])  # use original (untruncated) for stable hash
        key = (query, tid, repo_prefix)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)

        pairs.append([query, tid, repo_prefix])
        # If the same tid appeared before (same task+query, different run), keep first gold.
        if tid not in true_map:
            true_map[tid] = gold_files
        repos[repo_prefix] = ws_meta
        counts_by_source[source] += 1

    # Merge in extra pairs from --extra-pairs files (e.g. atelier session pairs).
    for ep_path in args.extra_pairs:
        ep = json.loads(Path(ep_path).read_text())
        for q, tid, rp in ep.get("pairs", []):
            key = (q, tid, rp)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            pairs.append([q, tid, rp])
            if tid not in true_map:
                true_map[tid] = ep.get("true_map", {}).get(tid, [])
            repos.setdefault(rp, ep.get("repos", {}).get(rp, {}))
            counts_by_source["session"] += 1

    # Include all known repos (even those absent from the JSONL) so synthetic
    # augmentation can reach the minimum for repos like atelier and linux that
    # have no SWE-bench tasks.
    for rp, ws_meta in known_repos.items():
        if rp not in repos:
            repos[rp] = ws_meta

    # Augment repos that are under the minimum threshold with synthetic pairs.
    if args.min_per_repo > 0:
        sys.path.insert(0, str(Path(__file__).parent))
        try:
            from synthetic_pair_miner import mine_synthetic_pairs
        except ImportError as e:
            print(f"[warn] synthetic_pair_miner not available: {e}", file=sys.stderr)
            mine_synthetic_pairs = None  # type: ignore[assignment]

        if mine_synthetic_pairs is not None:
            # Count real pairs per repo.
            real_by_repo: dict[str, int] = defaultdict(int)
            for _, _, rp in pairs:
                real_by_repo[rp] += 1

            syn_total = 0
            for repo_prefix, ws_meta in sorted(repos.items()):
                have = real_by_repo.get(repo_prefix, 0)
                need = args.min_per_repo - have
                if need <= 0:
                    continue
                ws = Path(ws_meta.get("ws", ""))
                if not ws.exists():
                    print(f"[synthetic] skip {repo_prefix}: ws not found", file=sys.stderr)
                    continue
                print(
                    f"[synthetic] {repo_prefix}: {have} real pairs, augmenting +{need}",
                    file=sys.stderr,
                )
                try:
                    syn_pairs, syn_true = mine_synthetic_pairs(
                        repo_dir=ws,
                        repo_prefix=repo_prefix,
                        max_queries_per_file=6,
                        max_files=300,
                        seed=42,
                        verbose=False,
                    )
                except Exception as exc:
                    print(f"[synthetic] {repo_prefix} failed: {exc}", file=sys.stderr)
                    continue

                added = 0
                for q, tid, rp in syn_pairs:
                    if added >= need:
                        break
                    key = (q, tid, rp)
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    pairs.append([q, tid, rp])
                    if tid not in true_map:
                        true_map[tid] = syn_true.get(tid, [])
                    added += 1
                syn_total += added
                counts_by_source["synthetic"] += added

            if syn_total:
                print(f"[synthetic] added {syn_total} pairs total", file=sys.stderr)

    out = {
        "gold_kind": "swebench",
        "pairs": pairs,
        "true_map": true_map,
        "repos": repos,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"Pairs:  {len(pairs)}")
    print(f"Repos:  {len(repos)}  ({', '.join(sorted(repos))})")
    for src, n in sorted(counts_by_source.items()):
        print(f"  {src:<25} {n}")
    if skipped_no_gold:
        print(f"Skipped (no gold):  {skipped_no_gold}")
    if skipped_no_ws:
        print(f"Skipped (no workspace): {dict(skipped_no_ws)}")
    print(f"Written -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
