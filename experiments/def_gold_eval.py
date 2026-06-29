"""Honest retrieval eval on a DEFINITION gold (not the SWE-edit gold).

For each atelier bench query, derive the gold automatically from the symbol index:
gold = files that DEFINE the *specific* symbols the query names (a symbol-name
defined in <= MAXDEF files, length >= MINLEN, to drop common tokens like 'symbol').
Queries that name no specific symbol are unscorable (skipped). Then score lexical
(tool_explore), semantic (fresh-embedded symbol_vectors), and fused vs that gold --
so we test 'find the code this query is about' instead of 'which file did the PR edit'.
"""

from __future__ import annotations

import json
import re
import signal
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")
from atelier.infra.embeddings.bge import BgeEmbedder

MAXDEF = 5
MINLEN = 4
KW = {
    "def",
    "class",
    "async",
    "return",
    "self",
    "import",
    "from",
    "none",
    "true",
    "false",
    "path",
    "name",
    "value",
    "data",
    "text",
    "line",
    "file",
    "type",
    "test",
}


def norm(p):
    return (p or "").replace("\\", "/")


def idents(q):
    return [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", q) if t.lower() not in KW]


def bucket(q):
    if "|" in q:
        return "alternation"
    if " " not in q.strip():
        return "single-token"
    return "multiword"


def rank_true(files, trues):
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) or t.endswith(norm(f)) for t in trues):
            return i
    return None


def rrf(rankings, k, limit):
    sc, best = {}, {}
    for files, w in rankings:
        for r, f in enumerate(files, 1):
            sc[f] = sc.get(f, 0.0) + w / (k + r)
            best[f] = min(best.get(f, r), r)
    return sorted(sc, key=lambda f: (-sc[f], best[f], f))[:limit]


def _alarm(s, f):
    raise TimeoutError


def main() -> int:
    from atelier.core.capabilities.code_context.engine import CodeContextEngine

    d = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
    meta = d["repos"]["atelier__atelier"]
    pairs = [q for q, _t, p in d["pairs"] if p == "atelier__atelier"]
    ws = Path(meta["ws"])
    eng = CodeContextEngine(ws, db_path=Path(meta["db"]), autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)
    eng._cache_set = lambda *a, **k: None
    eng._schema_ready = True

    c = sqlite3.connect(f"file:{meta['db']}?mode=ro", uri=True)
    sym2files: dict[str, set[str]] = {}
    rows = c.execute(
        "SELECT symbol_id,symbol_name,signature,file_path,start_byte,end_byte,"
        "COALESCE(doc_summary,'') FROM symbols WHERE repo_id=?",
        (eng.repo_id,),
    ).fetchall()
    c.close()
    for r in rows:
        if r[1]:
            sym2files.setdefault(r[1].lower(), set()).add(norm(r[3]))

    # fresh symbol embeddings (base text), avoids stale stored vectors
    fc: dict[str, bytes] = {}

    def src(fp, a, b):
        if fp not in fc:
            try:
                fc[fp] = (ws / fp).read_bytes()
            except OSError:
                fc[fp] = b""
        try:
            return fc[fp][a:b].decode("utf-8", "replace").strip().replace("\x00", " ")
        except Exception:  # noqa: BLE001
            return ""

    ids, file_of, texts = [], {}, []
    for r in rows:
        sid, name, sig, fp, a, b, doc = r[0], r[1] or "", r[2] or "", r[3] or "", r[4] or 0, r[5] or 0, r[6] or ""
        s = src(fp, a, b)
        parts = [name, sig, doc] if doc else ([name, sig, s[:200]] if s else [name, sig])
        t = "\n".join(p for p in parts if p).strip()
        if t:
            ids.append(sid)
            file_of[sid] = norm(fp)
            texts.append(t)
    model = BgeEmbedder()
    model.embed(["warm"])
    t0 = time.perf_counter()
    mat = np.asarray(model.embed(texts), np.float32)
    print(f"embedded {len(ids)} symbols in {time.perf_counter() - t0:.0f}s", file=sys.stderr)

    def def_gold(q):
        g = set()
        for t in idents(q):
            fs = sym2files.get(t.lower(), set())
            if 0 < len(fs) <= MAXDEF and len(t) >= MINLEN:
                g |= fs
        return g

    uq = sorted(set(pairs))
    qv = {q: v for q, v in zip(uq, np.asarray(model.embed_queries(uq), np.float32), strict=False)}

    def sem_files(v):
        order = np.argsort(-(mat @ v))
        out, seen = [], set()
        for i in order:
            f = file_of.get(ids[int(i)], "")
            if f and f not in seen:
                seen.add(f)
                out.append(f)
            if len(out) >= 10:
                break
        return out

    arms = ("lex", "sem", "fused", "oracle")
    agg = {a: [0.0, 0] for a in arms}
    byb = {}
    gsize = []
    scorable = 0
    for q in pairs:
        g = def_gold(q)
        if not g:
            continue
        scorable += 1
        gsize.append(len(g))
        gl = list(g)
        prev = signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, 5.0)
        lexf = []
        try:
            rr = eng.tool_explore(q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
            seen = set()
            for f in (x.get("path", "") for x in rr.get("files", [])):
                f = norm(f)
                if f and f not in seen:
                    seen.add(f)
                    lexf.append(f)
        except Exception:  # noqa: BLE001
            lexf = []
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, prev)
        semf = sem_files(qv[q])
        fusedf = rrf([(lexf, 1.0), (semf, 1.0)], 60, 10)
        rl, rs = rank_true(lexf, gl), rank_true(semf, gl)
        rf = rank_true(fusedf, gl)
        ro = min([r for r in (rl, rs) if r], default=None)
        bk = bucket(q)
        bb = byb.setdefault(bk, {a: [0.0, 0] for a in arms})
        for a, r in (("lex", rl), ("sem", rs), ("fused", rf), ("oracle", ro)):
            v = 1.0 / r if r else 0.0
            agg[a][0] += v
            agg[a][1] += 1
            bb[a][0] += v
            bb[a][1] += 1

    def m(x):
        return x[0] / max(x[1], 1)

    print(
        f"\n=== atelier DEFINITION-GOLD eval (scorable={scorable}/{len(pairs)}, avg gold files={sum(gsize) / max(len(gsize), 1):.1f}) ==="
    )
    print("  arm      MRR     vs SWE-edit-gold(lex 0.668)")
    print("  lex     %.4f" % m(agg["lex"]))
    print("  sem     %.4f" % m(agg["sem"]))
    print("  fused   %.4f   (lift %+.4f)" % (m(agg["fused"]), m(agg["fused"]) - m(agg["lex"])))
    print("  oracle  %.4f   (ceiling %+.4f)" % (m(agg["oracle"]), m(agg["oracle"]) - m(agg["lex"])))
    print("\n  by shape:        n     lex     sem   fused")
    for bk, bb in sorted(byb.items(), key=lambda kv: -kv[1]["lex"][1]):
        print("    %-12s %4d  %.3f  %.3f  %.3f" % (bk, bb["lex"][1], m(bb["lex"]), m(bb["sem"]), m(bb["fused"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
