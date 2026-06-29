"""Train repository-local top-five rerankers from indexed symbols.

This script never reads benchmark query pairs, task IDs, true maps, or gold
files. Positives come only from each repository's own symbol index: a generated
query names or describes a symbol, and that symbol's defining file is positive.

Run with ATELIER_SELF_SUPERVISED_TRAINING=1 and the experiment directory on
PYTHONPATH so V6 generates the candidate lists without applying a learned model.
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
import re
import shutil
import signal
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atelier.core.capabilities.code_context import CodeContextEngine
from atelier.core.capabilities.code_context.engine import (
    _ER_FEATURE_NAMES,
    _er_entry_features,
    _er_entry_path,
    _er_linear_score,
)

_DEFINITION_KINDS = {
    "async_function",
    "class",
    "function",
    "interface",
    "method",
    "struct",
    "trait",
    "type",
}
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SNAKE_RE = re.compile(r"[_\-]+")
_STOPWORDS = {
    "and",
    "are",
    "class",
    "def",
    "for",
    "from",
    "into",
    "return",
    "self",
    "that",
    "the",
    "this",
    "with",
}
_PATH_NOISE = frozenset({"src", "lib", "pkg", "init", "main", "test", "tests", "py"})

# Data-sufficiency thresholds. A reranker trained on a few hundred samples just
# memorises noise, so refuse anything below _MIN_SAMPLES and flag anything that
# does not reach _TARGET_SAMPLES.
_MIN_SAMPLES = 5000
_TARGET_SAMPLES = 10000


@dataclass(frozen=True)
class SymbolExample:
    symbol_id: str
    file_path: str
    symbol_name: str
    qualified_name: str
    kind: str
    signature: str
    doc_summary: str


@dataclass
class RankingExample:
    query: str
    positive_path: str
    candidates: list[dict[str, Any]]
    features: list[list[float]]
    positive_index: int


def _path_matches(candidate: str, positive: str) -> bool:
    left = candidate.replace("\\", "/")
    right = positive.replace("\\", "/")
    return left == right or left.endswith(f"/{right}") or right.endswith(f"/{left}")


def _stable_fraction(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _repo_metadata(project_root: Path, explicit_repos: list[str]) -> list[tuple[Path, Path | None]]:
    """Return (ws_path, db_path | None) pairs. Prefers repo_metadata.json for pre-built DBs."""
    meta_path = project_root / "experiments" / "retrieval_symbol_vote" / "repo_metadata.json"
    bench_path = project_root / "benchmarks" / "codebench" / "data" / "bench_pairs_multi.json"

    ws_to_db: dict[str, Path | None] = {}
    for path in (meta_path, bench_path):
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for meta in data.get("repos", {}).values():
            if not isinstance(meta, dict) or not meta.get("ws"):
                continue
            ws_key = str(Path(meta["ws"]).resolve())
            db_str = meta.get("db", "")
            if ws_key not in ws_to_db:
                ws_to_db[ws_key] = Path(db_str) if db_str else None
        break

    if explicit_repos:
        return [
            (ws := Path(r).expanduser().resolve(), ws_to_db.get(str(ws)))
            for r in explicit_repos
        ]

    result: list[tuple[Path, Path | None]] = []
    seen: set[str] = set()
    for ws_str, db in ws_to_db.items():
        if ws_str not in seen and Path(ws_str).is_dir():
            seen.add(ws_str)
            result.append((Path(ws_str), db))
    return result


def _load_symbols(
    engine: CodeContextEngine,
    max_symbols: int,
) -> list[SymbolExample]:
    with engine._connect(readonly=True) as connection:
        rows = connection.execute(
            """
            WITH frequencies AS (
                SELECT lower(symbol_name) AS normalized_name,
                       COUNT(DISTINCT file_path) AS file_count
                FROM symbols
                WHERE repo_id = ?
                GROUP BY lower(symbol_name)
            )
            SELECT symbols.symbol_id,
                   symbols.file_path,
                   symbols.symbol_name,
                   symbols.qualified_name,
                   lower(symbols.kind) AS kind,
                   symbols.signature,
                   symbols.doc_summary,
                   frequencies.file_count
            FROM symbols
            JOIN frequencies
              ON frequencies.normalized_name = lower(symbols.symbol_name)
            WHERE symbols.repo_id = ?
              AND length(symbols.symbol_name) >= 3
              AND frequencies.file_count <= 6
            ORDER BY frequencies.file_count ASC,
                     symbols.file_path ASC,
                     symbols.symbol_name ASC
            LIMIT ?
            """,
            (engine.repo_id, engine.repo_id, max_symbols * 4),
        ).fetchall()

    examples: list[SymbolExample] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        file_path = str(row["file_path"] or "")
        symbol_name = str(row["symbol_name"] or "")
        key = (file_path, symbol_name.lower())
        if (
            not file_path
            or not symbol_name
            or key in seen
            or "/vendor/" in f"/{file_path.lower()}/"
            or "/third_party/" in f"/{file_path.lower()}/"
        ):
            continue
        seen.add(key)
        examples.append(
            SymbolExample(
                symbol_id=str(row["symbol_id"] or ""),
                file_path=file_path,
                symbol_name=symbol_name,
                qualified_name=str(row["qualified_name"] or ""),
                kind=str(row["kind"] or ""),
                signature=str(row["signature"] or ""),
                doc_summary=str(row["doc_summary"] or ""),
            )
        )
        if len(examples) >= max_symbols:
            break
    return examples


def _split_name(name: str) -> list[str]:
    """Split CamelCase or snake_case into lowercase words, filtering short/stop words."""
    camel_split = _CAMEL_RE.sub(" ", name)
    words = _SNAKE_RE.sub(" ", camel_split).lower().split()
    return [w for w in words if len(w) >= 2 and w not in _STOPWORDS]


def _path_concepts(file_path: str) -> list[str]:
    """Extract meaningful module tokens from a file path (last 6 non-noise tokens)."""
    tokens: list[str] = []
    for part in Path(file_path).parts:
        stem = Path(part).stem
        for word in _split_name(stem):
            if word not in _PATH_NOISE:
                tokens.append(word)
    seen: set[str] = set()
    out: list[str] = []
    for t in reversed(tokens):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return list(reversed(out))[-6:]


def _doc_query(text: str) -> str | None:
    words: list[str] = []
    seen: set[str] = set()
    for raw in _WORD_RE.findall(text):
        normalized = raw.lower()
        if len(normalized) < 4 or normalized in _STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        words.append(raw)
        if len(words) >= 8:
            break
    if len(words) < 3:
        return None
    return " ".join(words)


def _query_variants(symbol: SymbolExample) -> list[str]:
    """Generate up to 8 fuzzy, real-world query variants for a symbol.

    Deliberately avoids exact symbol names so the reranker learns from
    hard cases rather than trivially-matchable tokens.
    """
    name = symbol.symbol_name
    name_words = _split_name(name)
    path_words = _path_concepts(symbol.file_path)

    variants: list[str] = []

    # 1. Decomposed name words — "load symbols" not "_load_symbols"
    if len(name_words) >= 2:
        variants.append(" ".join(name_words))

    # 2. Path context + name words — most realistic: "code context load symbols"
    if path_words and name_words:
        combo = (path_words[-2:] + name_words)[:6]
        variants.append(" ".join(combo))

    # 3. Typed prefix with kind keyword — "def load_sym", "class Config"
    if name_words and symbol.kind in _DEFINITION_KINDS:
        kw = "class" if symbol.kind == "class" else "def"
        prefix = "_".join(name_words[:2]) if len(name_words) >= 2 else name_words[0]
        variants.append(f"{kw} {prefix}")

    # 4. Regex alternation — real agent grep style: "load.*symbol|symbol.*load"
    if len(name_words) >= 2:
        a, b = name_words[0], name_words[-1]
        if a != b:
            variants.append(f"{a}.*{b}|{b}.*{a}")

    # 5. Doc-based prose query — semantic diversity
    doc_q = _doc_query(symbol.doc_summary)
    if doc_q:
        variants.append(doc_q)

    # 6. Signature param words — e.g. "engine max symbols" from func signature
    sig = symbol.signature.strip()
    if sig and len(sig) <= 200:
        sig_words = [
            w.lower()
            for w in _WORD_RE.findall(sig)
            if len(w) >= 4 and w.lower() not in _STOPWORDS and w.lower() != name.lower()
        ]
        if len(sig_words) >= 2:
            variants.append(" ".join(sig_words[:5]))

    # 7. Path only — file-finding style query
    if len(path_words) >= 3:
        variants.append(" ".join(path_words[-4:]))

    # 8. Partial qualified name — "module.method" from "pkg.module.Class.method"
    parts = symbol.qualified_name.split(".")
    if len(parts) >= 3:
        variants.append(".".join(parts[-2:]))

    # 9. Exact name — ONLY for non-trivial multi-word names (minority variant)
    if len(name) >= 8 and ("_" in name or any(c.isupper() for c in name[1:])):
        variants.append(name)

    # Deduplicate, filter trivially short
    output: list[str] = []
    seen: set[str] = set()
    for v in variants:
        normalized = v.strip()
        key = normalized.lower()
        if normalized and key not in seen and len(normalized) >= 5:
            seen.add(key)
            output.append(normalized)
    return output[:12]


_WORKER_ENGINE: CodeContextEngine | None = None
_WORKER_TIMEOUT_S = 0.0


def _auto_worker_count() -> int:
    """95% of available CPU cores (at least 1)."""
    try:
        cores = len(os.sched_getaffinity(0))
    except AttributeError:
        cores = os.cpu_count() or 8
    return max(1, int(cores * 0.95))


def _make_db_replicas(db_path: Path, count: int) -> list[Path]:
    """Create *count* private copies of the SQLite DB, one per worker process.

    Each worker reads its own file, so there is no cross-process SQLite
    connection/lock contention. The WAL is checkpointed into the main DB first;
    the -wal/-shm sidecars are also copied so each replica is a consistent
    snapshot regardless of checkpoint mode.
    """
    with contextlib.suppress(Exception):
        connection = sqlite3.connect(str(db_path))
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
    replicas: list[Path] = []
    for index in range(count):
        replica = db_path.with_name(f"{db_path.stem}.replica{index}{db_path.suffix}")
        for suffix in ("", "-wal", "-shm"):
            source = db_path.with_name(db_path.name + suffix)
            if source.exists():
                shutil.copyfile(source, replica.with_name(replica.name + suffix))
        replicas.append(replica)
    return replicas


def _cleanup_db_replicas(replicas: list[Path]) -> None:
    for replica in replicas:
        for suffix in ("", "-wal", "-shm"):
            with contextlib.suppress(OSError):
                replica.with_name(replica.name + suffix).unlink()


def _worker_init(replica_queue: Any, repo_root: str, timeout_s: float) -> None:
    """Bind a per-process engine to a unique DB replica claimed from the queue."""
    global _WORKER_ENGINE, _WORKER_TIMEOUT_S
    import atelier.core.capabilities.code_context.engine as engine_mod

    engine_mod._SEARCH_CHANNEL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
        max_workers=5,
        thread_name_prefix="atelier-fts-channel",
    )
    _WORKER_TIMEOUT_S = max(0.0, timeout_s)
    db_path = Path(replica_queue.get())
    engine = CodeContextEngine(Path(repo_root), db_path=db_path, autosync_enabled=False)
    engine._cache_get = lambda *_a, **_k: (False, None)
    engine._cache_set = lambda *_a, **_k: None
    engine._schema_ready = True
    with contextlib.suppress(Exception):
        engine._symbol_centrality_map()
    with contextlib.suppress(Exception):
        from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

        get_zoekt_supervisor(Path(repo_root))
    _WORKER_ENGINE = engine


def _collect_one(pair: tuple[SymbolExample, str]) -> tuple[str, RankingExample | None]:
    """Run one (symbol, query) probe inside a worker; returns (status, example)."""
    engine = _WORKER_ENGINE
    if engine is None:
        return ("missing", None)
    symbol, query = pair

    can_alarm = _WORKER_TIMEOUT_S > 0 and hasattr(signal, "SIGALRM")
    previous_handler: Any = None
    if can_alarm:

        def _on_alarm(_signum: int, _frame: Any) -> None:
            raise TimeoutError

        previous_handler = signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(max(1, math.ceil(_WORKER_TIMEOUT_S)))
    try:
        payload = engine.tool_explore(query, max_files=10, auto_index=False)
    except Exception:  # noqa: BLE001
        return ("missing", None)
    finally:
        if can_alarm:
            signal.alarm(0)
            if previous_handler is not None:
                signal.signal(signal.SIGALRM, previous_handler)

    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        return ("missing", None)
    candidates = [e for e in payload["files"][:8] if isinstance(e, dict) and _er_entry_path(e)]
    if len(candidates) < 2:
        return ("too_few", None)
    positive_index = next(
        (i for i, e in enumerate(candidates) if _path_matches(_er_entry_path(e), symbol.file_path)),
        None,
    )
    if positive_index is None:
        return ("missing", None)
    features = [_er_entry_features(query, e, r) for r, e in enumerate(candidates, 1)]
    return (
        "ok",
        RankingExample(
            query=query,
            positive_path=symbol.file_path,
            candidates=[],
            features=features,
            positive_index=positive_index,
        ),
    )


def _candidate_examples(
    repo_root: Path,
    db_path: Path,
    symbols: list[SymbolExample],
    max_examples: int,
    repo_id: str,
    workers: int = 0,
    timeout_s: float = 10.0,
) -> tuple[list[RankingExample], dict[str, int]]:
    """Collect ranking examples with a process pool, one DB replica per worker.

    tool_explore reads SQLite heavily; a ThreadPoolExecutor serialises on the
    GIL and a single shared connection. Separate processes (no GIL), each
    reading a private DB replica, remove that bottleneck and saturate cores.
    """
    resolved_workers = workers if workers > 0 else _auto_worker_count()

    ordered_symbols = sorted(
        symbols,
        key=lambda s: _stable_fraction(f"{repo_id}:{s.symbol_id}:{s.file_path}"),
    )
    all_pairs: list[tuple[SymbolExample, str]] = [
        (symbol, query) for symbol in ordered_symbols for query in _query_variants(symbol)
    ]

    stats: dict[str, int] = {
        "queries_attempted": 0,
        "positive_retrieved": 0,
        "positive_missing": 0,
        "too_few_candidates": 0,
        "workers": resolved_workers,
    }
    examples: list[RankingExample] = []
    if not all_pairs:
        return examples, stats

    from itertools import islice

    context_name = "fork" if sys.platform.startswith("linux") else "spawn"
    mp_context = multiprocessing.get_context(context_name)
    replicas = _make_db_replicas(db_path, resolved_workers)
    replica_queue: Any = mp_context.Queue()
    for replica in replicas:
        replica_queue.put(str(replica))

    total_bytes = sum(r.stat().st_size for r in replicas if r.exists())
    print(
        f"[train]   workers={resolved_workers} replicas={len(replicas)} "
        f"replica_disk={total_bytes / 1e6:.0f}MB pairs={len(all_pairs)}",
        flush=True,
    )

    pairs_iter = iter(all_pairs)
    batch = max(2, resolved_workers * 2)

    try:
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=resolved_workers,
            mp_context=mp_context,
            initializer=_worker_init,
            initargs=(replica_queue, str(repo_root), timeout_s),
        ) as executor:
            in_flight: dict[concurrent.futures.Future[tuple[str, RankingExample | None]], None] = {
                executor.submit(_collect_one, p): None for p in islice(pairs_iter, batch)
            }
            while in_flight:
                finished, _ = concurrent.futures.wait(
                    in_flight, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in finished:
                    del in_flight[future]
                    status, example = future.result()
                    stats["queries_attempted"] += 1
                    if stats["queries_attempted"] % 200 == 0:
                        print(
                            f"[train]   progress: attempted={stats['queries_attempted']} "
                            f"hits={stats['positive_retrieved']}",
                            flush=True,
                        )
                    if status == "too_few":
                        stats["too_few_candidates"] += 1
                    elif status == "ok" and example is not None:
                        stats["positive_retrieved"] += 1
                        examples.append(example)
                    else:
                        stats["positive_missing"] += 1

                if len(examples) >= max_examples:
                    for pending in in_flight:
                        pending.cancel()
                    break

                for p in islice(pairs_iter, batch - len(in_flight)):
                    in_flight[executor.submit(_collect_one, p)] = None
    finally:
        _cleanup_db_replicas(replicas)

    return examples, stats


def _split_examples(
    examples: list[RankingExample],
) -> tuple[list[RankingExample], list[RankingExample]]:
    train: list[RankingExample] = []
    validation: list[RankingExample] = []
    for example in examples:
        key = f"{example.query}\0{example.positive_path}"
        if _stable_fraction(key) < 0.2:
            validation.append(example)
        else:
            train.append(example)
    return train, validation


def _pairwise_rows(
    examples: list[RankingExample],
) -> list[list[float]]:
    rows: list[list[float]] = []
    for example in examples:
        positive = example.features[example.positive_index]
        for index, negative in enumerate(example.features):
            if index == example.positive_index:
                continue
            rows.append(
                [
                    positive_value - negative_value
                    for positive_value, negative_value in zip(
                        positive,
                        negative,
                        strict=True,
                    )
                ]
            )
    return rows


def _sigmoid_negative(value: float) -> float:
    if value >= 0:
        exponent = math.exp(-value)
        return exponent / (1.0 + exponent)
    exponent = math.exp(value)
    return 1.0 / (1.0 + exponent)


def _train_weights(
    rows: list[list[float]],
    seed: int,
    epochs: int,
    learning_rate: float,
    l2: float,
) -> list[float]:
    weights = [0.0] * len(_ER_FEATURE_NAMES)
    randomizer = random.Random(seed)
    order = list(range(len(rows)))

    for epoch in range(epochs):
        randomizer.shuffle(order)
        rate = learning_rate / math.sqrt(epoch + 1)
        for row_index in order:
            difference = rows[row_index]
            margin = sum(weight * value for weight, value in zip(weights, difference, strict=True))
            multiplier = _sigmoid_negative(margin)
            for index, value in enumerate(difference):
                weights[index] += rate * (multiplier * value - l2 * weights[index])
    return weights


def _rank_example(
    example: RankingExample,
    weights: list[float],
    blend: float,
    margin: float,
) -> int:
    scored: list[tuple[float, int]] = []
    for rank, features in enumerate(example.features, 1):
        learned = _er_linear_score(weights, features)
        combined = blend * learned + (1.0 - blend) * (1.0 / rank)
        scored.append((combined, rank))

    proposed = sorted(scored, key=lambda item: (-item[0], item[1]))
    if proposed[0][1] != 1:
        original_top_score = next(score for score, rank in scored if rank == 1)
        if proposed[0][0] - original_top_score < margin:
            proposed = sorted(scored, key=lambda item: item[1])

    original_positive_rank = example.positive_index + 1
    return next(
        new_rank
        for new_rank, (_score, original_rank) in enumerate(proposed, 1)
        if original_rank == original_positive_rank
    )


def _metrics(
    examples: list[RankingExample],
    weights: list[float] | None = None,
    blend: float = 0.0,
    margin: float = 0.0,
) -> dict[str, float | int]:
    reciprocal_rank = 0.0
    hit1 = 0
    hit3 = 0
    for example in examples:
        rank = example.positive_index + 1 if weights is None else _rank_example(example, weights, blend, margin)
        reciprocal_rank += 1.0 / rank
        hit1 += int(rank == 1)
        hit3 += int(rank <= 3)

    count = max(1, len(examples))
    return {
        "n": len(examples),
        "mrr": reciprocal_rank / count,
        "hit1": hit1 / count,
        "hit3": hit3 / count,
    }


def _choose_policy(
    validation: list[RankingExample],
    weights: list[float],
) -> tuple[float, float, dict[str, float | int], dict[str, float | int]]:
    baseline = _metrics(validation)
    best: tuple[float, float, dict[str, float | int]] | None = None

    for blend in (0.25, 0.5, 0.75, 1.0):
        for margin in (0.0, 0.01, 0.02, 0.05, 0.1):
            result = _metrics(validation, weights, blend, margin)
            if float(result["hit1"]) + 1e-12 < float(baseline["hit1"]):
                continue
            if float(result["hit3"]) + 1e-12 < float(baseline["hit3"]):
                continue
            candidate = (blend, margin, result)
            if best is None or (
                float(result["mrr"]),
                float(result["hit1"]),
                float(result["hit3"]),
                -margin,
            ) > (
                float(best[2]["mrr"]),
                float(best[2]["hit1"]),
                float(best[2]["hit3"]),
                -best[1],
            ):
                best = candidate

    if best is None:
        return 0.0, 0.0, baseline, baseline
    return best[0], best[1], baseline, best[2]


def _train_repository(
    repo_root: Path,
    max_symbols: int,
    max_examples: int,
    epochs: int,
    workers: int = 8,
    db_path: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    # Determine where to write the final model (alongside the benchmark DB)
    model_path = db_path.with_suffix(".explore_reranker.json") if db_path else None

    # Use a separate fresh DB for training to avoid stale-schema issues with benchmark DBs.
    # sst_ prefix = self-supervised training.
    if db_path:
        train_db = db_path.parent / f"sst_{db_path.stem}.db"
    else:
        train_db = Path(f"/tmp/sst_{repo_root.name}.db")
    model_path = model_path or (train_db.with_suffix(".explore_reranker.json"))

    print(f"[train] repository: {repo_root} train_db={train_db} model={model_path}", flush=True)
    engine = CodeContextEngine(repo_root, db_path=train_db, autosync_enabled=False)
    if not train_db.exists() or train_db.stat().st_size < 4096:
        engine.tool_index()

    symbols = _load_symbols(engine, max_symbols)
    print(f"[train]   symbols={len(symbols)} pairs={len(symbols)*8}", flush=True)
    examples, collection_stats = _candidate_examples(
        repo_root,
        train_db,
        symbols,
        max_examples,
        repo_id=str(engine.repo_id),
        workers=workers,
    )
    train, validation = _split_examples(examples)
    pairwise = _pairwise_rows(train)

    repo_id = str(engine.repo_id)
    report: dict[str, Any] = {
        "repo_id": repo_id,
        "repo_root": str(repo_root),
        "symbols": len(symbols),
        "examples": len(examples),
        "train_examples": len(train),
        "validation_examples": len(validation),
        "pairwise_rows": len(pairwise),
        "collection": collection_stats,
    }

    sample_count = len(examples)
    if sample_count >= _TARGET_SAMPLES:
        sample_status = "ok"
    elif sample_count >= _MIN_SAMPLES:
        sample_status = "low"
    else:
        sample_status = "insufficient"
    report["sample_status"] = sample_status
    print(
        f"[train]   SAMPLES examples={sample_count} status={sample_status} "
        f"(target={_TARGET_SAMPLES} min={_MIN_SAMPLES})",
        flush=True,
    )
    if sample_count < _MIN_SAMPLES:
        report["enabled"] = False
        report["reason"] = f"insufficient training samples: {sample_count} < {_MIN_SAMPLES} minimum"
        return report, model_path
    if len(train) < 100 or len(validation) < 30 or len(pairwise) < 200:
        report["enabled"] = False
        report["reason"] = "insufficient task-disjoint examples after split"
        return report, model_path

    weights = _train_weights(
        pairwise,
        seed=int(repo_id[:8], 16),
        epochs=epochs,
        learning_rate=0.06,
        l2=0.002,
    )
    blend, margin, baseline, learned = _choose_policy(validation, weights)
    mrr_gain = float(learned["mrr"]) - float(baseline["mrr"])
    enabled = (
        mrr_gain >= 0.005
        and float(learned["hit1"]) >= float(baseline["hit1"])
        and float(learned["hit3"]) >= float(baseline["hit3"])
    )

    report.update(
        {
            "enabled": enabled,
            "feature_names": list(_ER_FEATURE_NAMES),
            "weights": weights,
            "blend": blend,
            "margin": margin,
            "validation": {
                "baseline": baseline,
                "learned": learned,
                "mrr_gain": mrr_gain,
            },
        }
    )
    if not enabled:
        report["reason"] = "held-out synthetic validation did not clear safety gate"
    return report, model_path


def _write_model(report: dict[str, Any], model_path: Path) -> Path:
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return model_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="Repository path. Repeat to train selected repositories only.",
    )
    parser.add_argument("--max-symbols", type=int, default=8000)
    parser.add_argument("--max-examples", type=int, default=10000)
    parser.add_argument("--epochs", type=int, default=24)
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Parallel worker processes per repo (0 = auto: 95%% of CPU cores). Each owns a private DB replica.",
    )
    args = parser.parse_args()

    if os.environ.get("ATELIER_SELF_SUPERVISED_TRAINING") != "1":
        raise SystemExit("Run with ATELIER_SELF_SUPERVISED_TRAINING=1 so training uses unreranked V6 candidates.")

    project_root = Path(__file__).resolve().parents[2]
    repositories = _repo_metadata(project_root, args.repo)
    if not repositories:
        raise SystemExit("No benchmark repositories were found.")

    enabled = 0
    for repo_root, db_path in repositories:
        try:
            report, model_path = _train_repository(
                repo_root,
                max_symbols=max(100, args.max_symbols),
                max_examples=max(200, args.max_examples),
                epochs=max(1, args.epochs),
                workers=max(0, args.workers),
                db_path=db_path,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"[train] failed: {repo_root}: {exc}", flush=True)
            continue

        model_path = _write_model(report, model_path)
        enabled += int(bool(report.get("enabled")))
        validation = report.get("validation")
        print(
            f"[train] model={model_path} enabled={report.get('enabled')} "
            f"examples={report.get('examples')} validation={validation}",
            flush=True,
        )

    print(
        f"[train] complete repositories={len(repositories)} enabled_models={enabled}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
