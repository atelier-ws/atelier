"""Why does semantic under-perform on atelier? Stratify lex vs sem MRR by query
shape, and measure how much signal the per-symbol embedding text actually carries.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.embeddings.bge import BgeEmbedder

WANT = ("bge:BAAI/bge-code-v1", 1536)


def norm(p):
    return (p or "").replace("\\", "/")


def rank_true(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None


def bucket(q: str) -> str:
    if "|" in q:
        return "alternation (a|b|c)"
    if " " not in q.strip():
        return "single token"
    words = q.split()
    codey = sum(1 for w in words if "_" in w or re.search("[a-z][A-Z]", w) or re.search(r"[^\w\s]", w))
    return "multiword: code-ish" if codey else "multiword: NL-ish"


def _alarm(s, f):
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
    rid = eng.repo_id

    # ---- embedding-text richness (what we actually feed BGE per symbol) ----
    c = sqlite3.connect(f"file:{meta['db']}?mode=ro", uri=True)
    file_of = {r[0]: r[1] for r in c.execute("SELECT symbol_id, file_path FROM symbols")}
    cols = [r[1] for r in c.execute("PRAGMA table_info(symbols)")]
    has_doc = "doc_summary" in cols
    total, with_doc, avg_sig, avg_doc = c.execute(
        "SELECT COUNT(*),"
        " SUM(CASE WHEN doc_summary IS NOT NULL AND doc_summary!='' THEN 1 ELSE 0 END),"
        " AVG(LENGTH(COALESCE(signature,''))), AVG(LENGTH(COALESCE(doc_summary,'')))"
        " FROM symbols WHERE repo_id=?"
        if has_doc
        else "SELECT COUNT(*),0,AVG(LENGTH(COALESCE(signature,''))),0 FROM symbols WHERE repo_id=?",
        (rid,),
    ).fetchone()
    c.close()

    # ---- load vectors ----
    ids, vecs = [], []
    for vdb in (meta["db"], str(Path(meta["db"]).parent / "vectors.sqlite")):
        if not os.path.isfile(vdb):
            continue
        cc = sqlite3.connect(f"file:{vdb}?mode=ro", uri=True)
        try:
            rows = cc.execute(
                "SELECT symbol_id,vector_blob FROM symbol_vectors WHERE repo_id=? AND embedder_name=? AND embedding_dim=?",
                (rid, *WANT),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        cc.close()
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
    model = BgeEmbedder()
    model.embed(["warm"])

    B = {}
    wins = []  # queries where semantic strictly beats lexical
    losses = []  # semantic ranked, lexical ranked, sem much worse
    for q, tid in pairs:
        trues = tm.get(tid) or []
        if not trues:
            continue
        qv = np.asarray(model.embed_queries([q])[0], np.float32)
        order = np.argsort(-(mat @ qv))
        semf, seen = [], set()
        for i in order:
            f = norm(file_of.get(ids[int(i)], ""))
            if f and f not in seen:
                seen.add(f)
                semf.append(f)
            if len(semf) >= 10:
                break
        prev = signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, 5.0)
        lexf = []
        try:
            r = eng.tool_explore(q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
            seen = set()
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
        rl, rs = rank_true(lexf, trues), rank_true(semf, trues)
        bk = bucket(q)
        s = B.setdefault(bk, {"n": 0, "lex": 0.0, "sem": 0.0})
        s["n"] += 1
        s["lex"] += 1 / rl if rl else 0
        s["sem"] += 1 / rs if rs else 0
        if rs and (not rl or rs < rl):
            wins.append((q, rl, rs))
        if rl and rl <= 3 and (not rs or rs > 5):
            losses.append((q, rl, rs))

    print("\n=== embedding-text richness (per-symbol input to BGE) ===")
    print(
        f"  symbols={total}  with doc_summary={with_doc} ({100 * with_doc / max(total, 1):.0f}%)"
        f"  avg signature={avg_sig:.0f} chars  avg doc={avg_doc:.0f} chars"
    )
    print(
        "  => render_embedding_text = name + signature + doc(or 200ch source);"
        " with little doc, the vector is ~name+signature (near-lexical)."
    )

    print("\n=== MRR by query shape (atelier) ===")
    print("  %-22s %5s %8s %8s %8s" % ("bucket", "n", "lex", "sem", "sem-lex"))
    for bk, s in sorted(B.items(), key=lambda kv: -kv[1]["n"]):
        lm, sm = s["lex"] / s["n"], s["sem"] / s["n"]
        print("  %-22s %5d %8.3f %8.3f %+8.3f" % (bk, s["n"], lm, sm, sm - lm))
    tot_n = sum(s["n"] for s in B.values())
    print("  --")
    print(
        "  %-22s %5d %8.3f %8.3f"
        % ("ALL", tot_n, sum(s["lex"] for s in B.values()) / tot_n, sum(s["sem"] for s in B.values()) / tot_n)
    )

    print(f"\n=== where semantic BEATS lexical (n={len(wins)}/{tot_n}) -- sample ===")
    for q, rl, rs in wins[:8]:
        print(f"  sem#{rs} lex#{rl}: {q[:70]!r}")
    print(f"\n=== where lexical wins big, semantic misses (n={len(losses)}/{tot_n}) -- sample ===")
    for q, rl, rs in losses[:8]:
        print(f"  lex#{rl} sem#{rs}: {q[:70]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
