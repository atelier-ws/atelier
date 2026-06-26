from __future__ import annotations

import json
import math
import os
import re

if os.environ.get("ATELIER_EXPERIMENT_SYMBOL_VOTE") == "1":
    from atelier.core.capabilities.code_context import engine as E

    C = E.CodeContextEngine
    if not getattr(C, "_v9", False):
        original_tool_explore = C.tool_explore
        Z = C._zoekt_candidate_files
        FD = [None]
        ID = re.compile("[A-Za-z_][A-Za-z0-9_]*")
        DF = re.compile("\\b(?P<k>def|class)\\s+(?P<n>[A-Za-z_][A-Za-z0-9_]*)")
        TEST = re.compile("(^|/)(tests?|testing|specs?)(/|$)|(^|/)test_[^/]+$|_test\\.", re.I)
        AUX = re.compile(
            "(^|/)(docs?|documentation|examples?|galleries|benchmarks?|vendor|third_party)(/|$)|\\.(md|rst|ipynb|json)$",
            re.I,
        )
        STOP = set(
            "and as assert async await break case class continue def del else except false finally for from if import in is lambda none not or pass raise return self super true try while with yield the this that these those then than into onto when where which what without within should could would have has had does did done make using used use value values result results file files code name string object method function".split()
        )

        def uq(xs, n):
            o = []
            s = set()
            for x in xs:
                x = str(x).strip()
                k = x.lower()
                if x and k not in s:
                    s.add(k)
                    o.append(x)
                if len(o) >= n:
                    break
            return o

        def parts(x):
            o = []
            for a in re.split("[./:_-]+", x):
                for b in re.sub("([a-z0-9])([A-Z])", "\\1 \\2", a).split():
                    b = b.lower()
                    if len(b) >= 2 and b not in STOP:
                        o.append(b)
            return o

        def parse(q):
            ds = [(m.group("k"), m.group("n")) for m in DF.finditer(q)]
            ids = [n for _, n in ds]
            for a in q.split("|"):
                a = re.sub("\\\\[bBAZz]$", "", a.strip())
                a = re.sub("^\\^|\\$$", "", a).strip("()[]{}?+*")
                if re.fullmatch("[A-Za-z_][A-Za-z0-9_.]*", a):
                    ids.append(a.rsplit(".", 1)[-1])
            ids += [
                x
                for x in ID.findall(q)
                if len(x) >= 3 and x.lower() not in STOP and ("_" in x or any(c.isupper() for c in x[1:]))
            ]
            if E._is_precise_symbol_query(q.strip()):
                ids.append(q.strip().rsplit(".", 1)[-1])
            ids = uq(ids, 12)
            comps = uq((p for x in ids for p in parts(x)), 16)
            terms = uq(
                [
                    *ids,
                    *comps,
                    *[str(x).lower() for x in E._query_terms(q) if len(str(x)) >= 3 and str(x).lower() not in STOP],
                ],
                14,
            )
            intent = (
                "definition"
                if ds
                else "symbol"
                if E._is_precise_symbol_query(q.strip())
                else "code"
                if ids or "|" in q
                else "prose"
            )
            return (
                intent,
                ds,
                ids,
                comps,
                terms,
                bool(re.search("\\btest|pytest|unittest|spec\\b", q, re.I)),
                bool(re.search("\\bdoc|example|gallery|benchmark|readme\\b", q, re.I)),
            )

        def gram(x):
            x = re.sub("[^a-z0-9]+", "", x.lower())
            return {x[i : i + 3] for i in range(max(0, len(x) - 2))}

        def sim(a, b):
            x, y = (gram(a), gram(b))
            return len(x & y) / len(x | y) if x and y else 0.0

        def cv(t, ts):
            t = t.lower()
            return sum(x.lower() in t for x in ts) / len(ts) if ts else 0.0

        def emit(x):
            p = os.environ.get("ATELIER_EXPERIMENT_DIAGNOSTICS", "")
            if not p:
                return
            try:
                if FD[0] is None:
                    FD[0] = os.open(p, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644)
                os.write(FD[0], (json.dumps(x, sort_keys=True, separators=(",", ":")) + "\n").encode())
            except OSError:
                pass

        def cap(self, q, *, path=".", max_files=40):
            f = Z(self, q, path=path, max_files=max(max_files, 96))
            self.__dict__["_v9z"] = (q, f)
            return f[:max_files]

        def exact(self, ids, ds):
            if not ids:
                return ([], {})
            ts = {x.lower() for x in ids}
            mk = ",".join("?" for _ in ts)
            try:
                with self._connect(readonly=True) as c:
                    r = c.execute(
                        f"SELECT file_path,lower(symbol_name) n,lower(kind) k FROM symbols WHERE repo_id=? AND lower(symbol_name) IN ({mk})",
                        (self.repo_id, *ts),
                    ).fetchall()
            except Exception:  # noqa: BLE001
                return ([], {})
            exp = {n.lower(): k for k, n in ds}
            d = {}
            for x in r:
                p = str(x["file_path"] or "")
                n = str(x["n"] or "")
                k = str(x["k"] or "")
                if not p:
                    continue
                z = d.setdefault(p, {"n": set(), "k": 0.0})
                z["n"].add(n)
                z["k"] = max(
                    z["k"],
                    float(
                        (exp.get(n) == "class" and k == "class")
                        or (exp.get(n) == "def" and k in {"function", "method"})
                    ),
                )
            out = {
                p: {"confidence": min(1, 0.72 * len(z["n"]) / max(1, len(ids)) + 0.28 * z["k"]), "kind": z["k"]}
                for p, z in d.items()
            }
            return (sorted(out, key=lambda p: (-out[p]["confidence"], p))[:70], out)

        def anchors(self, ids):
            d = {}
            for a in ids[:3]:
                try:
                    f = Z(self, a, path=".", max_files=32)
                except Exception:  # noqa: BLE001
                    f = []
                for i, p in enumerate(f, 1):
                    z = d.setdefault(p, {"a": set(), "r": 0.0})
                    z["a"].add(a.lower())
                    z["r"] += 1 / (8 + i)
            out = {
                p: {"confidence": min(1, 0.75 * len(z["a"]) / max(1, min(3, len(ids))) + 0.25 * min(1, z["r"] * 6))}
                for p, z in d.items()
            }
            return (sorted(out, key=lambda p: (-out[p]["confidence"], p))[:80], out)

        def lines(self, terms):
            if not terms:
                return ([], {})
            ts = [x.lower() for x in terms[:12]]
            q = " OR ".join('"' + x.replace('"', '""')[:80] + '"' for x in ts)
            d = {}
            try:
                with self._connect(readonly=True) as c:
                    r = c.execute(
                        "SELECT file_path,text,bm25(file_line_fts) rank FROM file_line_fts WHERE file_line_fts MATCH ? AND repo_id=? ORDER BY rank LIMIT 1200",
                        (q, self.repo_id),
                    ).fetchall()
            except Exception:  # noqa: BLE001
                return ([], {})
            for x in r:
                p = str(x["file_path"] or "")
                t = str(x["text"] or "").lower()
                if not p or E.is_generated_path(p):
                    continue
                h = {a for a in ts if a in t}
                if not h:
                    continue
                z = d.setdefault(p, {"c": set(), "h": 0, "m": 0.0})
                z["c"].update(h)
                z["h"] += 1
                z["m"] = max(z["m"], len(h) / max(1, len(ts)))
            out = {}
            for p, z in d.items():
                fc = len(z["c"]) / max(1, len(ts))
                rep = min(1, math.log1p(z["h"]) / math.log(13))
                out[p] = {"confidence": min(1, 0.6 * fc + 0.28 * z["m"] + 0.12 * rep), "coverage": fc}
            return (sorted(out, key=lambda p: (-out[p]["confidence"], -out[p]["coverage"], p))[:100], out)

        def union(ch):
            out = []
            seen = set()
            names = ["baseline", "line", "anchors", "zoekt", "exact"]
            i = 0
            while len(out) < 80:
                add = False
                for n in names:
                    f = ch[n]
                    if i < len(f) and f[i] not in seen:
                        seen.add(f[i])
                        out.append(f[i])
                        add = True
                if not add and all(i >= len(ch[n]) for n in names):
                    break
                i += 1
            return out

        def syms(self, ids, comps, terms, ds, cs):
            if not cs:
                return {}
            mk = ",".join("?" for _ in cs)
            out = {}
            exp = {n.lower(): k for k, n in ds}
            il = {x.lower() for x in ids}
            try:
                with self._connect(readonly=True) as c:
                    r = c.execute(
                        f"SELECT file_path,symbol_name,qualified_name,lower(kind) k,signature,doc_summary FROM symbols WHERE repo_id=? AND file_path IN ({mk})",
                        (self.repo_id, *cs),
                    ).fetchall()
            except Exception:  # noqa: BLE001
                return {}
            for x in r:
                p = str(x["file_path"] or "")
                n = str(x["symbol_name"] or "")
                qn = str(x["qualified_name"] or "")
                k = str(x["k"] or "")
                if not p:
                    continue
                z = out.setdefault(p, {"e": 0.0, "f": 0.0, "c": 0.0, "s": 0.0, "d": 0.0, "k": 0.0})
                ns = [n, qn]
                z["e"] = max(z["e"], max((float(a.lower() in il) for a in ns), default=0))
                z["f"] = max(z["f"], max((sim(a, b) for a in ids for b in ns), default=0))
                z["c"] = max(z["c"], max((cv(a, comps) for a in ns), default=0))
                z["s"] = max(z["s"], cv(str(x["signature"] or ""), terms))
                z["d"] = max(z["d"], cv(str(x["doc_summary"] or ""), terms))
                z["k"] = max(
                    z["k"],
                    float(
                        (exp.get(n.lower()) == "class" and k == "class")
                        or (exp.get(n.lower()) == "def" and k in {"function", "method"})
                    ),
                )
            return out

        def explore(self, q, *a, **kw):
            self.__dict__.pop("_v9z", None)
            r = original_tool_explore(self, q, *a, **kw)
            if not isinstance(r, dict) or not isinstance(r.get("files"), list) or (not r["files"]):
                return r
            mf = max(1, min(int(kw.get("max_files", 6)), 10))
            en = {}
            base = []
            for e in r["files"]:
                if isinstance(e, dict):
                    p = str(e.get("path") or e.get("file_path") or "")
                    if p and p not in en:
                        en[p] = e
                        base.append(p)
            z = self.__dict__.get("_v9z")
            zo = list(z[1]) if isinstance(z, tuple) and z[0] == q else []
            intent, ds, ids, comps, terms, wt, wa = parse(q)
            ex, ed = exact(self, ids, ds)
            an, ad = anchors(self, ids)
            li, ld = lines(self, terms)
            ch = {"baseline": base, "zoekt": zo, "exact": ex, "anchors": an, "line": li}
            cs = union(ch)
            sd = syms(self, ids, comps, terms, ds, cs)
            rk = {n: {p: i for i, p in enumerate(f, 1)} for n, f in ch.items()}
            W = {
                "definition": [1, 0.8, 1.4, 1, 1],
                "symbol": [1.1, 1, 1.3, 1, 0.8],
                "code": [0.9, 0.9, 0.7, 1.1, 1.4],
                "prose": [0.8, 0.9, 0.2, 0.35, 1.7],
            }[intent]
            names = ["baseline", "zoekt", "exact", "anchors", "line"]
            sc = {}
            xp = {}
            for p in cs:
                rs = 0.0
                sup = 0
                for n, w in zip(names, W, strict=True):
                    v = rk[n].get(p)
                    if v is not None:
                        rs += w / (10 + v)
                        sup += v <= 40
                s = sd.get(p, {})
                sym = min(
                    1,
                    0.45 * s.get("e", 0)
                    + 0.2 * s.get("f", 0)
                    + 0.12 * s.get("c", 0)
                    + 0.1 * s.get("s", 0)
                    + 0.05 * s.get("d", 0)
                    + 0.08 * s.get("k", 0),
                )
                line = ld.get(p, {}).get("confidence", 0)
                exa = ed.get(p, {}).get("confidence", 0)
                anc = ad.get(p, {}).get("confidence", 0)
                path = max((float(x.lower() in p.lower()) for x in ids), default=0)
                de = 0.4 * exa + 0.36 * sym + 0.14 * path + 0.1 * anc
                ce = 0.58 * line + 0.22 * sym + 0.12 * path + 0.08 * anc
                le = 0.5 * anc + 0.3 / (1 + rk["zoekt"].get(p, 100)) + 0.2 / (1 + rk["baseline"].get(p, 100))
                best = de if intent in {"definition", "symbol"} else ce if intent == "prose" else max(ce, 0.9 * le)
                score = 0.5 * rs + 0.32 * best + 0.1 * min(1, sup / 3) + 0.05 * sym + 0.03 * path
                if not wt and TEST.search(p) and (sup < 2):
                    score *= 0.76
                if not wa and AUX.search(p) and (sup < 2):
                    score *= 0.7
                sc[p] = score
                xp[p] = {"d": de, "c": ce, "l": le}
            order = sorted(cs, key=lambda p: (-sc[p], rk["baseline"].get(p, 999), rk["line"].get(p, 999), p))
            sel = []
            rem = list(order)
            while rem and len(sel) < mf:
                if not sel or len(sel) >= 3:
                    x = rem[0]
                else:
                    top = sc[rem[0]]
                    cand = [p for p in rem[:15] if sc[p] >= top * 0.9]
                    used = {max(xp[p], key=xp[p].get) for p in sel}
                    x = max(
                        cand, key=lambda p: (sc[p] + (0.015 if max(xp[p], key=xp[p].get) not in used else 0), sc[p], p)
                    )
                sel.append(x)
                rem.remove(x)
            out = dict(r)
            out["files"] = [
                en.get(p, {"path": p, "language": "unknown", "symbols": [], "source_sections": []}) for p in sel
            ]
            out["experiment"] = {"name": "fast_union_v9", "intent": intent}
            emit(
                {
                    "version": "v9_fast_union",
                    "repo_root": str(self.repo_root.resolve()),
                    "query": q,
                    "channels": {n: f[:80] for n, f in ch.items()},
                    "candidate_union": cs,
                    "final": sel,
                    "raw_order": order[:80],
                }
            )
            return out

        C._zoekt_candidate_files = cap
        C.tool_explore = explore
        C._v9 = True
