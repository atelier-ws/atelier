"""Train the GLOBAL LambdaMART explore reranker (real + synthetic).

One global tree model across all repositories (per-repo models are unreliable
at this data scale). Candidate generation is plain V6 (run with
ATELIER_SELF_SUPERVISED_TRAINING=1 so the engine does not apply an existing
reranker during collection). Features are computed with the engine's own
``_er_entry_features`` so training matches serving exactly.

Data:
  - real:      patch-derived gold from real_training_pairs.jsonl (label 1 if a
               candidate path is in gold_files).
  - synthetic: symbol-mined queries (label 1 if candidate is the symbol's file).

Validation is on HELD-OUT REAL TASK IDS ONLY. Synthetic groups always train.
The model deploys only if it clears the safety gate:
  validation MRR gain >= --min-mrr-gain, Hit@3 not decreased, p95 inference < 1ms.

Run:
  ATELIER_SELF_SUPERVISED_TRAINING=1 \
  PYTHONPATH=experiments/retrieval_symbol_vote \
  uv run python experiments/retrieval_symbol_vote/train_global_lambdamart.py
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import math
import multiprocessing
import os
import random
import signal
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

# Reuse symbol mining + query-variant generation from the self-supervised
# trainer (same engine features). Collection itself is local to this module:
# workers share the existing read-only index (no replication, no re-indexing).
import train_self_supervised_reranker as syn

_WORKER_ENGINE: Any = None
_WORKER_TIMEOUT_S = 0.0


def _worker_init_shared(repo_root: str, db_path: str, timeout_s: float) -> None:
    """Bind a per-process engine to the SHARED read-only index.

    Each worker opens its own SQLite connection to the same file. Collection is
    read-only (tool_explore with auto_index=False), and SQLite serves many
    concurrent readers without lock contention — so no per-worker DB replica is
    needed (the base indexes can be multi-GB; replicating them would be ruinous).
    """
    global _WORKER_ENGINE, _WORKER_TIMEOUT_S
    import atelier.core.capabilities.code_context.engine as engine_mod

    engine_mod._SEARCH_CHANNEL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
        max_workers=5,
        thread_name_prefix="atelier-fts-channel",
    )
    _WORKER_TIMEOUT_S = max(0.0, timeout_s)
    engine = CodeContextEngine(Path(repo_root), db_path=Path(db_path), autosync_enabled=False)
    engine._cache_get = lambda *_a, **_k: (False, None)
    engine._cache_set = lambda *_a, **_k: None
    engine._schema_ready = True
    with contextlib.suppress(Exception):
        engine._symbol_centrality_map()
    with contextlib.suppress(Exception):
        from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

        get_zoekt_supervisor(Path(repo_root))
    _WORKER_ENGINE = engine
import xgboost as xgb

from atelier.core.capabilities.code_context import CodeContextEngine
from atelier.core.capabilities.code_context.engine import (
    _ER_FEATURE_NAMES,
    _er_entry_features,
    _er_entry_path,
    _er_linear_score,
    _er_tree_score,
)

_TOP_K = 8
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _stable_fraction(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _matches_any(candidate: str, gold: tuple[str, ...]) -> bool:
    norm = _normalize(candidate)
    for raw in gold:
        g = _normalize(raw)
        if norm == g or norm.endswith(f"/{g}") or g.endswith(f"/{norm}"):
            return True
    return False


# --------------------------------------------------------------------------
# Parallel candidate collection (process pool, one DB replica per worker)
# --------------------------------------------------------------------------


def _collect_probe(probe: tuple[str, tuple[str, ...]]) -> dict[str, Any] | None:
    """Run one (query, gold) probe in a worker; returns a ranking group or None.

    None means the probe is unusable for reranking: query failed, fewer than 2
    candidates, or the gold file was absent from V6's top-K (candidate-recall
    failure — tracked separately by the caller).
    """
    query, gold = probe
    engine = _WORKER_ENGINE
    if engine is None:
        return None

    can_alarm = _WORKER_TIMEOUT_S > 0 and hasattr(signal, "SIGALRM")
    previous: Any = None
    if can_alarm:

        def _on_alarm(_signum: int, _frame: Any) -> None:
            raise TimeoutError

        previous = signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(max(1, math.ceil(_WORKER_TIMEOUT_S)))
    try:
        payload = engine.tool_explore(query, max_files=12, auto_index=False)
    except Exception:  # noqa: BLE001
        return None
    finally:
        if can_alarm:
            signal.alarm(0)
            if previous is not None:
                signal.signal(signal.SIGALRM, previous)

    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        return None
    candidates = [e for e in payload["files"][:_TOP_K] if isinstance(e, dict) and _er_entry_path(e)]
    if len(candidates) < 2:
        return None
    labels = [1 if _matches_any(_er_entry_path(e), gold) else 0 for e in candidates]
    if not any(labels):
        return None
    features = [_er_entry_features(query, e, rank) for rank, e in enumerate(candidates, 1)]
    return {"features": features, "labels": labels}


def _collect_repo_groups(
    repo_root: Path,
    db_path: Path,
    probes: list[tuple[str, tuple[str, ...]]],
    workers: int,
    timeout_s: float,
) -> list[dict[str, Any] | None]:
    """Collect groups for all *probes* of one repo; order matches *probes*."""
    if not probes:
        return []
    resolved = workers if workers > 0 else syn._auto_worker_count()
    context_name = "fork" if sys.platform.startswith("linux") else "spawn"
    mp_context = multiprocessing.get_context(context_name)
    print(f"[glm]   workers={resolved} shared_db={db_path} probes={len(probes)}", flush=True)

    results: list[dict[str, Any] | None] = []
    chunksize = max(1, len(probes) // (resolved * 8))
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=resolved,
        mp_context=mp_context,
        initializer=_worker_init_shared,
        initargs=(str(repo_root), str(db_path), timeout_s),
    ) as executor:
        for index, result in enumerate(executor.map(_collect_probe, probes, chunksize=chunksize), 1):
            results.append(result)
            if index % 500 == 0:
                hits = sum(1 for r in results if r is not None)
                print(f"[glm]   progress {index}/{len(probes)} usable={hits}", flush=True)
    return results


# --------------------------------------------------------------------------
# Group assembly
# --------------------------------------------------------------------------


def _load_real_corpus(path: Path, excluded: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        task_id = str(record.get("task_id") or "")
        query = str(record.get("query") or "").strip()
        prefix = str(record.get("repo_prefix") or "")
        gold = record.get("gold_files")
        if not task_id or not query or not prefix or not isinstance(gold, list):
            continue
        if task_id in excluded:
            continue
        key = (prefix, task_id, query)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {"task_id": task_id, "repo_prefix": prefix, "query": query, "gold_files": [str(g) for g in gold if str(g)]}
        )
    return out


def _excluded_task_ids(paths: list[Path]) -> set[str]:
    out: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                out.add(value)
    return out


# --------------------------------------------------------------------------
# Tree export + metrics
# --------------------------------------------------------------------------


def _export_trees(booster: xgb.Booster) -> list[dict[str, Any]]:
    """Flatten an XGBoost booster into the serving tree format (parallel arrays)."""
    trees: list[dict[str, Any]] = []
    for raw in booster.get_dump(dump_format="json", with_stats=False):
        root = json.loads(raw)
        by_id: dict[int, dict[str, Any]] = {}
        stack = [root]
        while stack:
            node = stack.pop()
            by_id[int(node["nodeid"])] = node
            stack.extend(node.get("children", []))
        ids = sorted(by_id)
        remap = {nid: i for i, nid in enumerate(ids)}
        size = len(ids)
        feature = [-1] * size
        threshold = [0.0] * size
        left = [-1] * size
        right = [-1] * size
        leaf = [0.0] * size
        for nid in ids:
            i = remap[nid]
            node = by_id[nid]
            if "leaf" in node:
                feature[i] = -1
                leaf[i] = float(node["leaf"])
            else:
                split = str(node["split"])
                feature[i] = int(split[1:]) if split.startswith("f") else int(split)
                threshold[i] = float(node["split_condition"])
                left[i] = remap[int(node["yes"])]
                right[i] = remap[int(node["no"])]
        trees.append({"feature": feature, "threshold": threshold, "left": left, "right": right, "leaf": leaf})
    return trees


def _fit_linear(train_groups: list[dict[str, Any]], seed: int, epochs: int) -> tuple[list[float], int]:
    """Fit a pairwise-logistic linear ranker (the 'simpler approach').

    For each query, every positive-minus-negative feature difference is a +1
    training example; SGD drives those margins positive. Returns (weights,
    pairwise_row_count).
    """
    n_features = len(_ER_FEATURE_NAMES)
    rows: list[list[float]] = []
    for group in train_groups:
        feats = group["features"]
        labels = group["labels"]
        positives = [f for f, label in zip(feats, labels, strict=True) if label == 1]
        negatives = [f for f, label in zip(feats, labels, strict=True) if label == 0]
        for pos in positives:
            for neg in negatives:
                rows.append([float(p) - float(n) for p, n in zip(pos, neg, strict=True)])
    weights = [0.0] * n_features
    randomizer = random.Random(seed)
    order = list(range(len(rows)))
    learning_rate = 0.05
    l2 = 0.002
    for epoch in range(epochs):
        randomizer.shuffle(order)
        rate = learning_rate / math.sqrt(epoch + 1)
        for index in order:
            diff = rows[index]
            margin = sum(w * d for w, d in zip(weights, diff, strict=True))
            # sigmoid(-margin): logistic gradient wanting margin > 0
            mult = 1.0 / (1.0 + math.exp(margin)) if margin >= 0 else math.exp(-margin) / (1.0 + math.exp(-margin))
            for j, d in enumerate(diff):
                weights[j] += rate * (mult * d - l2 * weights[j])
    return weights, len(rows)


def _group_rank(scores: list[float], labels: list[int]) -> int:
    """Best (lowest) rank of any positive after sorting by score desc (stable)."""
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    for position, idx in enumerate(order, 1):
        if labels[idx] == 1:
            return position
    return len(scores) + 1


def _baseline_rank(labels: list[int]) -> int:
    for index, label in enumerate(labels, 1):
        if label == 1:
            return index
    return len(labels) + 1


def _metrics(ranks: list[int]) -> dict[str, float]:
    if not ranks:
        return {"n": 0, "mrr": 0.0, "hit1": 0.0, "hit3": 0.0}
    n = len(ranks)
    return {
        "n": n,
        "mrr": sum(1.0 / r for r in ranks) / n,
        "hit1": sum(1 for r in ranks if r == 1) / n,
        "hit3": sum(1 for r in ranks if r <= 3) / n,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus", default=str(_PROJECT_ROOT / "experiments/retrieval_symbol_vote/real_training_pairs.jsonl")
    )
    parser.add_argument(
        "--repo-metadata", default=str(_PROJECT_ROOT / "experiments/retrieval_symbol_vote/repo_metadata.json")
    )
    parser.add_argument(
        "--exclude-task-ids",
        action="append",
        default=[str(_PROJECT_ROOT / "experiments/retrieval_symbol_vote/eval_task_ids.txt")],
    )
    parser.add_argument("--max-symbols", type=int, default=3000)
    parser.add_argument("--max-syn-probes", type=int, default=6000, help="Cap on synthetic probes per repo.")
    parser.add_argument("--no-synthetic", action="store_true")
    parser.add_argument("--workers", type=int, default=0, help="0 = auto (95%% of cores).")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--min-mrr-gain", type=float, default=0.005)
    parser.add_argument("--max-latency-ms", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repo", action="append", default=[], help="Only train on these repo prefixes (repeatable).")
    parser.add_argument("--min-train-groups", type=int, default=50)
    parser.add_argument("--min-val-groups", type=int, default=10)
    parser.add_argument("--out", default="", help="Model output path (default: bundled engine package path).")
    parser.add_argument("--model", choices=["lambdamart", "linear"], default="lambdamart")
    parser.add_argument(
        "--groups-cache", default="", help="Cache collected groups here; reuse if present (skips collection)."
    )
    parser.add_argument("--linear-epochs", type=int, default=30)
    args = parser.parse_args()

    if os.environ.get("ATELIER_SELF_SUPERVISED_TRAINING") != "1":
        raise SystemExit("Run with ATELIER_SELF_SUPERVISED_TRAINING=1 so candidates are raw V6 (no reranker applied).")

    if args.out:
        out_path = Path(args.out)
    else:
        import atelier.core.capabilities.code_context.engine as engine_mod

        out_path = Path(engine_mod.__file__).resolve().parent / "explore_reranker_model.json"

    excluded = _excluded_task_ids([Path(p) for p in args.exclude_task_ids])
    corpus = _load_real_corpus(Path(args.corpus), excluded)
    metadata = json.loads(Path(args.repo_metadata).read_text(encoding="utf-8"))
    repos = metadata.get("repos", metadata)

    by_repo: dict[str, list[dict[str, Any]]] = {}
    for record in corpus:
        by_repo.setdefault(record["repo_prefix"], []).append(record)

    groups: list[dict[str, Any]] = []
    recall_fail = {"real": 0, "synthetic": 0}
    randomizer = random.Random(args.seed)
    cache_path = Path(args.groups_cache) if args.groups_cache else None

    if cache_path and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        groups = cached["groups"]
        recall_fail = cached.get("recall_fail", recall_fail)
        print(f"[glm] loaded {len(groups)} cached groups from {cache_path} (skipping collection)", flush=True)

    for prefix in sorted(repos) if not groups else []:
        if args.repo and prefix not in args.repo:
            continue
        meta = repos.get(prefix)
        if not isinstance(meta, dict) or not meta.get("ws") or not meta.get("db"):
            continue
        repo_root = Path(str(meta["ws"])).resolve()
        base_db = Path(str(meta["db"])).resolve()
        if not repo_root.is_dir():
            print(f"[glm] skip {prefix}: workspace missing", flush=True)
            continue
        # Collection only READS the index, so workers share the existing base
        # index via independent read-only connections (SQLite serves concurrent
        # readers without contention). No replication (base DBs can be multi-GB)
        # and no re-indexing. Build a small glm_ index only if none exists.
        if base_db.exists() and base_db.stat().st_size > 4096:
            train_db = base_db
            engine = CodeContextEngine(repo_root, db_path=train_db, autosync_enabled=False)
            print(f"[glm] using existing index {train_db} ({base_db.stat().st_size / 1e6:.0f}MB, shared read-only)", flush=True)
        else:
            train_db = base_db.parent / f"glm_{base_db.stem}.db"
            engine = CodeContextEngine(repo_root, db_path=train_db, autosync_enabled=False)
            if not train_db.exists() or train_db.stat().st_size < 4096:
                print(f"[glm] indexing {prefix} -> {train_db}", flush=True)
                engine.tool_index()

        real_records = by_repo.get(prefix, [])
        real_probes = [(r["query"], tuple(r["gold_files"])) for r in real_records]
        print(f"[glm] repo={prefix} real_probes={len(real_probes)}", flush=True)
        real_results = _collect_repo_groups(repo_root, train_db, real_probes, args.workers, args.timeout)
        for record, result in zip(real_records, real_results, strict=True):
            if result is None:
                recall_fail["real"] += 1
            else:
                groups.append({**result, "task_id": record["task_id"], "source": "real"})

        if not args.no_synthetic:
            symbols = syn._load_symbols(engine, args.max_symbols)
            syn_probes: list[tuple[str, tuple[str, ...]]] = []
            for symbol in symbols:
                for query in syn._query_variants(symbol):
                    syn_probes.append((query, (symbol.file_path,)))
            randomizer.shuffle(syn_probes)
            syn_probes = syn_probes[: args.max_syn_probes]
            print(f"[glm] repo={prefix} synthetic_probes={len(syn_probes)}", flush=True)
            syn_results = _collect_repo_groups(repo_root, train_db, syn_probes, args.workers, args.timeout)
            for result in syn_results:
                if result is None:
                    recall_fail["synthetic"] += 1
                else:
                    groups.append({**result, "task_id": f"synthetic::{prefix}", "source": "synthetic"})

    if cache_path and not cache_path.exists() and groups:
        cache_path.write_text(json.dumps({"groups": groups, "recall_fail": recall_fail}), encoding="utf-8")
        print(f"[glm] cached {len(groups)} groups -> {cache_path}", flush=True)

    real_groups = [g for g in groups if g["source"] == "real"]
    syn_groups = [g for g in groups if g["source"] == "synthetic"]
    print(
        f"[glm] usable groups: real={len(real_groups)} synthetic={len(syn_groups)} total={len(groups)} "
        f"| recall-failures real={recall_fail['real']} synthetic={recall_fail['synthetic']}",
        flush=True,
    )

    real_task_ids = sorted({g["task_id"] for g in real_groups})
    val_tasks = {t for t in real_task_ids if _stable_fraction(f"val:{t}") < 0.2}
    if real_task_ids and not val_tasks:
        val_tasks.add(real_task_ids[-1])
    train_groups = [g for g in groups if not (g["source"] == "real" and g["task_id"] in val_tasks)]
    val_groups = [g for g in real_groups if g["task_id"] in val_tasks]
    print(
        f"[glm] split: train_groups={len(train_groups)} (real_tasks={len(real_task_ids) - len(val_tasks)} + synthetic) "
        f"val_groups={len(val_groups)} (val_tasks={len(val_tasks)})",
        flush=True,
    )

    report: dict[str, Any] = {
        "groups_real": len(real_groups),
        "groups_synthetic": len(syn_groups),
        "recall_failures": recall_fail,
        "train_groups": len(train_groups),
        "val_groups": len(val_groups),
        "val_tasks": len(val_tasks),
    }

    if len(train_groups) < args.min_train_groups or len(val_groups) < args.min_val_groups:
        report["enabled"] = False
        report["reason"] = f"insufficient groups (train={len(train_groups)}, val={len(val_groups)})"
        print(json.dumps(report, indent=2), flush=True)
        raise SystemExit("Not enough usable groups to train; see report above.")

    # Train the chosen ranker over the same groups: a 40-tree LambdaMART
    # (default) or the simpler pairwise-logistic linear model. Both score the
    # same 14 features and are applied identically at serving.
    trees: list[dict[str, Any]] = []
    weights: list[float] = []
    booster = None
    if args.model == "linear":
        weights, n_pairs = _fit_linear(train_groups, seed=args.seed, epochs=args.linear_epochs)
        report["pairwise_rows"] = n_pairs

        def _score(feats: list[float]) -> float:
            return _er_linear_score(weights, feats)
    else:
        rows: list[list[float]] = []
        labels: list[float] = []
        group_sizes: list[int] = []
        for group in train_groups:
            feats = group["features"]
            group_sizes.append(len(feats))
            for feat, label in zip(feats, group["labels"], strict=True):
                rows.append([float(x) for x in feat])
                labels.append(float(label))
        dtrain = xgb.DMatrix(np.asarray(rows, dtype=np.float32), label=np.asarray(labels, dtype=np.float32))
        dtrain.set_group(group_sizes)
        params = {
            "objective": "rank:ndcg",
            "tree_method": "hist",
            "max_depth": 3,
            "eta": 0.05,
            "min_child_weight": 5,
            "subsample": 0.8,
            "colsample_bytree": 0.9,
            "lambda": 5.0,
            "alpha": 0.2,
            "lambdarank_pair_method": "mean",
            "lambdarank_num_pair_per_sample": 4,
            "nthread": 4,
            "seed": args.seed,
        }
        booster = xgb.train(params, dtrain, num_boost_round=40)
        trees = _export_trees(booster)

        def _score(feats: list[float]) -> float:
            return _er_tree_score(trees, feats)

    # Evaluate on held-out real tasks with the serving scorer.
    base_ranks: list[int] = []
    learned_ranks: list[int] = []
    for group in val_groups:
        feats = [[float(x) for x in f] for f in group["features"]]
        lbls = [int(x) for x in group["labels"]]
        scores = [_score(f) for f in feats]
        base_ranks.append(_baseline_rank(lbls))
        learned_ranks.append(_group_rank(scores, lbls))

    baseline = _metrics(base_ranks)
    learned = _metrics(learned_ranks)
    mrr_gain = learned["mrr"] - baseline["mrr"]

    # Parity check (tree only): exported-tree order vs native xgboost order.
    parity_mismatch = 0
    if booster is not None:
        for group in val_groups:
            feats = [[float(x) for x in f] for f in group["features"]]
            lbls = [int(x) for x in group["labels"]]
            xgb_scores = list(booster.predict(xgb.DMatrix(np.asarray(feats, dtype=np.float32))))
            if _group_rank(xgb_scores, lbls) != _group_rank([_score(f) for f in feats], lbls):
                parity_mismatch += 1

    # Latency: time scoring a representative 8-candidate group with serving fn.
    sample = [[float(x) for x in f] for f in val_groups[0]["features"]]
    timings: list[float] = []
    for _ in range(3000):
        start = time.perf_counter()
        for f in sample:
            _score(f)
        timings.append((time.perf_counter() - start) * 1000.0)
    timings.sort()
    p95_ms = timings[int(0.95 * len(timings)) - 1]

    enabled = mrr_gain >= args.min_mrr_gain and learned["hit3"] >= baseline["hit3"] and p95_ms < args.max_latency_ms
    report.update(
        {
            "enabled": enabled,
            "model": args.model,
            "trees": len(trees),
            "validation": {"baseline": baseline, "learned": learned, "mrr_gain": mrr_gain},
            "latency_p95_ms": round(p95_ms, 4),
            "export_parity_mismatch": parity_mismatch,
        }
    )
    if not enabled:
        reasons = []
        if mrr_gain < args.min_mrr_gain:
            reasons.append(f"mrr_gain {mrr_gain:.4f} < {args.min_mrr_gain}")
        if learned["hit3"] < baseline["hit3"]:
            reasons.append("hit3 regressed")
        if p95_ms >= args.max_latency_ms:
            reasons.append(f"p95 {p95_ms:.3f}ms >= {args.max_latency_ms}ms")
        report["reason"] = "; ".join(reasons)

    model = {
        "model_type": "lambdamart_trees" if args.model == "lambdamart" else "linear",
        "version": 2,
        "enabled": enabled,
        "feature_names": list(_ER_FEATURE_NAMES),
        "window": _TOP_K,
        "metadata": report,
    }
    if args.model == "linear":
        model["weights"] = weights
        model["blend"] = 1.0
        model["margin"] = 0.0
    else:
        model["trees"] = trees
    report_path = _PROJECT_ROOT / f"experiments/retrieval_symbol_vote/global_{args.model}_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if enabled:
        out_path.write_text(json.dumps(model) + "\n", encoding="utf-8")
        print(f"[glm] DEPLOYED -> {out_path}", flush=True)
    else:
        staged = report_path.with_suffix(".model_disabled.json")
        staged.write_text(json.dumps(model) + "\n", encoding="utf-8")
        print(f"[glm] gate NOT cleared; staged disabled model -> {staged}", flush=True)

    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
