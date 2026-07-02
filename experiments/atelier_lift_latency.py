"""Atelier: semantic-channel lift vs per-query latency.

Per query (realistic single-query serving, BGE model resident on GPU):
  * semantic = BGE query embed + cosine over symbol_vectors + project symbol->file
  * lexical  = tool_explore (lexical+zoekt as wired today)
  * fused    = RRF(lexical, semantic)
Reports MRR per arm AND latency (embed / cosine / explore) so we can say
"+X MRR for +Y ms".
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.embeddings.bge import BgeEmbedder

WANT = ("bge:BAAI/bge-code-v1", 1536)


def norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def load_vecs(main_db: str, rid: str):
    c = sqlite3.connect(f"file:{main_db}?mode=ro", uri=True)
    file_of = {r[0]: r[1] for r in c.execute("SELECT symbol_id, file_path FROM symbols")}
    c.close()
    ids: list[str] = []
    vecs: list[list[float]] = []
    for vdb in (main_db, str(Path(main_db).parent / "vectors.sqlite")):
        if not os.path.isfile(vdb):
            continue
        c = sqlite3.connect(f"file:{vdb}?mode=ro", uri=True)
        try:
            rows = c.execute(
                "SELECT symbol_id,vector_blob FROM symbol_vectors WHERE repo_id=? AND embedder_name=? AND embedding_dim=?",
                (rid, *WANT),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        c.close()
        if rows:
            for sid, blob in rows:
                if sid not in file_of:
                    continue
                if not isinstance(blob, (bytes, bytearray, memoryview)):
                    continue
                blob = bytes(blob)
                if len(blob) != WANT[1] * 4:
                    continue
                ids.append(sid)
                vecs.append(np.frombuffer(blob, dtype=np.float32))
            break
    mat = np.vstack(vecs).astype(np.float32) if vecs else np.zeros((0, WANT[1]), np.float32)
    return ids, mat, file_of


def rrf(rankings, k, limit):
    score: dict[str, float] = {}
    best: dict[str, int] = {}
    for files, w in rankings:
        for rank, f in enumerate(files, 1):
            score[f] = score.get(f, 0.0) + w / (k + rank)
            best[f] = min(best.get(f, rank), rank)
    return sorted(score, key=lambda f: (-score[f], best[f], f))[:limit]


def rank_true(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None


def pct(v, p):
    s = sorted(v)
    return s[min(len(s) - 1, int(p / 100 * (len(s) - 1)))] if s else 0.0


def _alarm(signum, frame):
    raise TimeoutError


def main() -> int:
    d = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
    meta = d["repos"]["atelier__atelier"]
    tm = d["true_map"]
    pairs = [(q, t) for q, t, p in d["pairs"] if p == "atelier__atelier"]
    eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)
    eng._cache_set = lambda *a, **k: None
    eng._schema_ready = True
    ids, mat, file_of = load_vecs(meta["db"], eng.repo_id)
    print(f"atelier vectors={mat.shape[0]}  queries={len(pairs)}", file=sys.stderr)
    model = BgeEmbedder()
    model.embed(["warmup"])
    for _ in range(3):
        model.embed_queries(["warm cuda kernels"])

    agg = {a: {"rr": 0.0, "h1": 0, "h3": 0, "n": 0} for a in ("lex", "sem", "fused", "oracle")}
    lat = {"embed": [], "cosine": [], "sem": [], "lex": []}

    def add(a, r):
        agg[a]["n"] += 1
        if r:
            agg[a]["rr"] += 1 / r
            agg[a]["h1"] += r == 1
            agg[a]["h3"] += r <= 3

    for q, tid in pairs:
        trues = tm.get(tid) or []
        if not trues:
            continue
        t0 = time.perf_counter()
        qv = np.asarray(model.embed_queries([q])[0], np.float32)
        te = time.perf_counter()
        scores = mat @ qv
        order = np.argsort(-scores)
        semf, seen = [], set()
        for i in order:
            f = norm(file_of.get(ids[int(i)], ""))
            if f and f not in seen:
                seen.add(f)
                semf.append(f)
            if len(semf) >= 10:
                break
        tc = time.perf_counter()
        lat["embed"].append((te - t0) * 1000)
        lat["cosine"].append((tc - te) * 1000)
        lat["sem"].append((tc - t0) * 1000)
        prev = signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, 5.0)
        tl = time.perf_counter()
        lexf, seen = [], set()
        try:
            r = eng.tool_explore(q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
            for f in (x.get("path", "") for x in r.get("files", [])):
                f = norm(f)
                if f and f not in seen:
                    seen.add(f)
                    lexf.append(f)
        except Exception:  # noqa: BLE001
            lexf = []
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, prev)
        lat["lex"].append((time.perf_counter() - tl) * 1000)
        fused = rrf([(lexf[:10], 1.0), (semf[:10], 1.0)], 60, 10)
        rl, rs = rank_true(lexf[:10], trues), rank_true(semf[:10], trues)
        add("lex", rl)
        add("sem", rs)
        add("fused", rank_true(fused, trues))
        add("oracle", min([r for r in (rl, rs) if r], default=None))

    def mrr(a):
        return agg[a]["rr"] / max(agg[a]["n"], 1)

    print("\n=== atelier (n=%d) ===" % agg["lex"]["n"])
    for a in ("lex", "sem", "fused", "oracle"):
        print(
            "  %-7s MRR=%.4f hit@1=%.3f hit@3=%.3f"
            % (a, mrr(a), agg[a]["h1"] / max(agg[a]["n"], 1), agg[a]["h3"] / max(agg[a]["n"], 1))
        )
    print("  semantic lift (fused - lexical) = %+.4f MRR" % (mrr("fused") - mrr("lex")))
    print("\n=== latency ms (per query, model resident on GPU) ===")
    for k in ("embed", "cosine", "sem", "lex"):
        v = lat[k]
        print("  %-7s mean=%.2f p50=%.2f p95=%.2f" % (k, sum(v) / len(v), pct(v, 50), pct(v, 95)))
    print(
        "  -> semantic channel adds ~{:.1f} ms p50 (embed+cosine) for {:+.4f} MRR (fused vs lexical)".format(pct(lat["sem"], 50), mrr("fused") - mrr("lex"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
