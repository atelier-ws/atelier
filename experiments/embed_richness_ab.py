"""#2 test: does a RICHER per-symbol embedding text help semantic retrieval?

Self-contained A/B (no DB writes, no stored-vector staleness): embed every atelier
symbol TWICE on the GPU --
  base = name + signature + (doc OR 200ch source)   [what ships today]
  rich = name + signature + doc + up to N chars of the BODY
-- then score semantic file-MRR for each on the same atelier bench queries.
Reads the symbols table + source files directly (no engine import, so a concurrent
engine.py edit can't break it).
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")
from atelier.infra.embeddings.bge import BgeEmbedder

BODY_CHARS = 1200


def norm(p):
    return (p or "").replace("\\", "/")


def rank_true(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None


def bucket(q):
    if "|" in q:
        return "alternation"
    if " " not in q.strip():
        return "single-token"
    words = q.split()
    codey = sum(1 for w in words if "_" in w or re.search("[a-z][A-Z]", w) or re.search(r"[^\w\s]", w))
    return "multiword-codey" if codey else "multiword-NLish"


def main() -> int:
    d = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
    meta = d["repos"]["atelier__atelier"]
    tm = d["true_map"]
    pairs = [(q, t) for q, t, p in d["pairs"] if p == "atelier__atelier"]
    ws = Path(meta["ws"])

    c = sqlite3.connect(f"file:{meta['db']}?mode=ro", uri=True)
    cols = {r[1] for r in c.execute("PRAGMA table_info(symbols)")}
    need = ["symbol_id", "symbol_name", "signature", "file_path", "start_byte", "end_byte"]
    doc_col = "doc_summary" if "doc_summary" in cols else None
    sel = ",".join(need + ([doc_col] if doc_col else []))
    rows = c.execute(f"SELECT {sel} FROM symbols").fetchall()
    c.close()

    filecache: dict[str, bytes] = {}

    def source_of(fp, a, b):
        if fp not in filecache:
            try:
                filecache[fp] = (ws / fp).read_bytes()
            except OSError:
                filecache[fp] = b""
        try:
            return filecache[fp][a:b].decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return ""

    ids, file_of, base_texts, rich_texts = [], {}, [], []
    n_doc = 0
    for r in rows:
        sid, name, sig, fp, a, bb = r[0], r[1] or "", r[2] or "", r[3] or "", r[4] or 0, r[5] or 0
        doc = (r[6] or "") if doc_col else ""
        src = source_of(fp, a, bb).strip().replace("\x00", " ")
        base_parts = [name, sig]
        if doc:
            base_parts.append(doc)
            n_doc += 1
        elif src:
            base_parts.append(src[:200])
        base = "\n".join(p for p in base_parts if p).strip()
        rich_parts = [name, sig]
        if doc:
            rich_parts.append(doc)
        if src:
            rich_parts.append(src[:BODY_CHARS])
        rich = "\n".join(p for p in rich_parts if p).strip()
        if not base:
            continue
        ids.append(sid)
        file_of[sid] = fp
        base_texts.append(base)
        rich_texts.append(rich)

    print(
        f"symbols embedded={len(ids)}  with_doc={n_doc} ({100 * n_doc / max(len(ids), 1):.0f}%)  body_chars={BODY_CHARS}",
        file=sys.stderr,
    )
    print(
        f"avg len: base={sum(map(len, base_texts)) // max(len(base_texts), 1)}  "
        f"rich={sum(map(len, rich_texts)) // max(len(rich_texts), 1)} chars",
        file=sys.stderr,
    )

    model = BgeEmbedder()
    model.embed(["warm"])
    t0 = time.perf_counter()
    base_mat = np.asarray(model.embed(base_texts), np.float32)
    print(f"base corpus embedded in {time.perf_counter() - t0:.0f}s", file=sys.stderr)
    t0 = time.perf_counter()
    rich_mat = np.asarray(model.embed(rich_texts), np.float32)
    print(f"rich corpus embedded in {time.perf_counter() - t0:.0f}s", file=sys.stderr)

    # one query embed batch, reused for both corpora
    uq = sorted({q for q, _ in pairs})
    qvecs = {q: v for q, v in zip(uq, np.asarray(model.embed_queries(uq), np.float32), strict=False)}

    def sem_files(qv, mat):
        order = np.argsort(-(mat @ qv))
        out, seen = [], set()
        for i in order:
            f = norm(file_of.get(ids[int(i)], ""))
            if f and f not in seen:
                seen.add(f)
                out.append(f)
            if len(out) >= 10:
                break
        return out

    res = {"base": {}, "rich": {}}
    for q, tid in pairs:
        trues = tm.get(tid) or []
        if not trues:
            continue
        bk = bucket(q)
        for variant, mat in (("base", base_mat), ("rich", rich_mat)):
            r = rank_true(sem_files(qvecs[q], mat), trues)
            s = res[variant].setdefault(bk, {"n": 0, "rr": 0.0})
            s["n"] += 1
            s["rr"] += 1 / r if r else 0

    print("\n=== semantic file-MRR: base vs rich (atelier) ===")
    print("  %-18s %5s %8s %8s %8s" % ("bucket", "n", "base", "rich", "delta"))
    allb = {"n": 0, "b": 0.0, "r": 0.0}
    for bk in sorted(res["base"], key=lambda k: -res["base"][k]["n"]):
        n = res["base"][bk]["n"]
        bm = res["base"][bk]["rr"] / n
        rm = res["rich"][bk]["rr"] / n
        allb["n"] += n
        allb["b"] += res["base"][bk]["rr"]
        allb["r"] += res["rich"][bk]["rr"]
        print("  %-18s %5d %8.3f %8.3f %+8.3f" % (bk, n, bm, rm, rm - bm))
    print("  --")
    print(
        "  %-18s %5d %8.3f %8.3f %+8.3f"
        % ("ALL", allb["n"], allb["b"] / allb["n"], allb["r"] / allb["n"], (allb["r"] - allb["b"]) / allb["n"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
