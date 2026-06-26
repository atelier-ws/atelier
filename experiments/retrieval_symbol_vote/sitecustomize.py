"""Generic structural hybrid retrieval experiment (no benchmark/gold knowledge)."""
from __future__ import annotations
import json, math, os, re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DEF = re.compile(r"\b(?P<kind>def|class)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
QUOTED = re.compile(r"""(?P<q>["'])(?P<v>.*?)(?P=q)""")
TEST = re.compile(r"(^|/)(tests?|testing|specs?)(/|$)|(^|/)test_[^/]+$", re.I)
AUX = re.compile(r"(^|/)(docs?(?:-internal)?|documentation|examples?|galleries|benchmarks?|frontend|vendor|third_party)(/|$)|\.(?:md|rst|ipynb|json|lock)$", re.I)
STOP = {"and","as","assert","async","await","break","case","class","continue","def","del","do","else","except","false","finally","for","from","if","import","in","is","lambda","none","not","or","pass","raise","return","self","super","true","try","while","with","yield"}
PROSE_STOP = STOP | {"the","this","that","these","those","then","than","into","onto","when","where","which","what","without","within","should","could","would","have","has","had","does","did","done","make","using","used","use","value","values","result","results","file","files","code","name","string","object","method","function"}
_DIAG_FD: int | None = None

@dataclass(frozen=True)
class Plan:
    intent: str
    definitions: tuple[tuple[str,str], ...]
    identifiers: tuple[str, ...]
    anchors: tuple[str, ...]
    terms: tuple[str, ...]
    literals: tuple[str, ...]
    wants_tests: bool
    wants_aux: bool

def shaped(s: str) -> bool:
    return "_" in s or s.isupper() or any(c.isupper() for c in s[1:])

def dedupe(xs: Iterable[str], n: int) -> tuple[str, ...]:
    out=[]; seen=set()
    for x in xs:
        x=str(x).strip(); low=x.lower()
        if not x or low in seen: continue
        seen.add(low); out.append(x)
        if len(out)>=n: break
    return tuple(out)

def parse(engine_mod: Any, q: str) -> Plan:
    defs=tuple((m.group("kind"),m.group("name")) for m in DEF.finditer(q))
    alts=[]
    for seg in q.split("|"):
        m=DEF.search(seg)
        raw=m.group("name") if m else re.sub(r"\\[bBAZz]$","",seg.strip())
        raw=re.sub(r"^\^|\$$","",raw)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",raw) and raw.lower() not in STOP: alts.append(raw)
    ids=[t for t in IDENT.findall(q) if len(t)>=3 and t.lower() not in STOP and shaped(t)]
    norm=q.strip()
    if engine_mod._is_precise_symbol_query(norm): alts.append(norm.rsplit(".",1)[-1])
    lits=[m.group("v").strip() for m in QUOTED.finditer(q) if m.group("v").strip()]
    prose=[str(t) for t in engine_mod._query_terms(q) if len(str(t))>=3 and str(t).lower() not in PROSE_STOP]
    names=[name for _kind,name in defs]
    identifiers=dedupe([*names,*alts,*ids],18); anchors=dedupe([*names,*alts,*ids],8); literals=dedupe(lits,8)
    intent="definition" if defs else "symbol" if engine_mod._is_precise_symbol_query(norm) else "code" if identifiers or "|" in q else "prose"
    terms=dedupe([*identifiers,*literals] if intent in {"definition","symbol"} else [*identifiers,*literals,*prose] if intent=="code" else [*literals,*prose],16)
    return Plan(intent,defs,identifiers,anchors,terms,literals,bool(re.search(r"\btest(?:_|s\b|ing\b)|\bspec(?:_|s\b)|pytest|unittest|tearDown|setUp|TestCase|Tests\b",q,re.I)),bool(re.search(r"\bdocs?|documentation|example|gallery|benchmark|frontend|javascript|typescript|readme\b",q,re.I)))

def path_parts(p: str) -> set[str]: return {x for x in re.split(r"[/._-]+",p.lower()) if x}
def phrase(s: str) -> str: return '"'+s.replace('"','""')+'"'

def walk_files(v: Any):
    if isinstance(v,dict):
        if v.get("file_path") or v.get("path"): yield v
        for x in v.values(): yield from walk_files(x)
    elif isinstance(v,(list,tuple)):
        for x in v: yield from walk_files(x)

def diag(payload: dict[str,Any]) -> None:
    global _DIAG_FD
    target=os.environ.get("ATELIER_EXPERIMENT_DIAGNOSTICS","").strip()
    if not target: return
    try:
        if _DIAG_FD is None: _DIAG_FD=os.open(target,os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o644)
        os.write(_DIAG_FD,(json.dumps(payload,sort_keys=True,separators=(",",":"))+"\n").encode())
    except Exception: pass

def install() -> None:
    if os.environ.get("ATELIER_EXPERIMENT_SYMBOL_VOTE")!="1": return
    from atelier.core.capabilities.code_context import engine as em
    cls=em.CodeContextEngine
    if getattr(cls,"_structural_hybrid_experiment_installed",False): return
    original=cls.tool_explore; original_zoekt=cls._zoekt_candidate_files

    def capture(self: Any,q: str,*,path: str=".",max_files: int=40):
        files=original_zoekt(self,q,path=path,max_files=max(max_files,96)); self.__dict__["_v7_zoekt"]=(q,files); return files[:max_files]

    def exact(self: Any,p: Plan):
        if not p.identifiers: return [],{}
        toks={x.lower():x for x in p.identifiers}; marks=','.join('?' for _ in toks)
        try:
            with self._connect(readonly=True) as c:
                rows=c.execute(f"""WITH m AS (SELECT file_path,lower(symbol_name) token,lower(kind) kind FROM symbols WHERE repo_id=? AND lower(symbol_name) IN ({marks})), f AS (SELECT token,COUNT(DISTINCT file_path) df FROM m GROUP BY token) SELECT m.file_path,m.token,m.kind,f.df FROM m JOIN f USING(token)""",(self.repo_id,*toks)).fetchall()
        except Exception: return [],{}
        defs=set(getattr(em,"_DEFINITION_KINDS",{"class","function","method"})); expected={n.lower():k for k,n in p.definitions}; d={}; seen=set()
        for r in rows:
            path=str(r["file_path"] or ""); token=str(r["token"] or ""); kind=str(r["kind"] or "")
            if not path or not token or (path,token,kind) in seen: continue
            seen.add((path,token,kind)); df=max(1,int(r["df"] or 1)); x=d.setdefault(path,{"tokens":set(),"defs":set(),"kind":set(),"idf":0.0,"df":df})
            x["tokens"].add(token); x["idf"]+=math.log1p(1+1/df); x["df"]=min(x["df"],df)
            if kind in defs: x["defs"].add(token)
            if (expected.get(token)=="class" and kind=="class") or (expected.get(token)=="def" and kind in {"function","method"}): x["kind"].add(token)
        ni=max(1,len(p.identifiers)); nd=max(1,len(p.definitions))
        for x in d.values(): x["confidence"]=min(1.0,.42*len(x["tokens"])/ni+.30*len(x["kind"])/nd+.16*len(x["defs"])/ni+.12*min(1.0,x["idf"]/ni))
        order=sorted(d,key=lambda z:(-d[z]["confidence"],-len(d[z]["kind"]),-len(d[z]["tokens"]),d[z]["df"],z))
        return order[:96],{z:{"kind_matches":sorted(d[z]["kind"]),"confidence":d[z]["confidence"]} for z in order}

    def anchors(self: Any,p: Plan):
        cache=self.__dict__.setdefault("_v7_anchor_cache",{}); d={}
        for a in p.anchors:
            files=cache.get(a)
            if files is None:
                try: files=original_zoekt(self,a,path=".",max_files=40)
                except Exception: files=[]
                cache[a]=files
            for rank,path in enumerate(files,1):
                x=d.setdefault(path,{"anchors":set(),"rrf":0.0,"rank":rank}); x["anchors"].add(a.lower()); x["rrf"]+=1/(8+rank); x["rank"]=min(x["rank"],rank)
        n=max(1,len(p.anchors)); ceiling=n/9
        for x in d.values(): x["confidence"]=min(1.0,.72*len(x["anchors"])/n+.28*min(1.0,x["rrf"]/ceiling))
        order=sorted(d,key=lambda z:(-d[z]["confidence"],-len(d[z]["anchors"]),d[z]["rank"],z))
        return order[:96],{z:{"confidence":d[z]["confidence"]} for z in order}

    def lines(self: Any,p: Plan):
        if not p.terms: return [],{}
        terms=[x.lower() for x in p.terms]; oq=' OR '.join(phrase(x) for x in terms); aq=' AND '.join(phrase(x) for x in terms[:8]); rows=[]
        try:
            with self._connect(readonly=True) as c:
                if len(terms)>=2: rows += [(r,True) for r in c.execute("SELECT file_path,line,text,bm25(file_line_fts) rank FROM file_line_fts WHERE file_line_fts MATCH ? AND repo_id=? ORDER BY rank LIMIT 700",(aq,self.repo_id)).fetchall()]
                rows += [(r,False) for r in c.execute("SELECT file_path,line,text,bm25(file_line_fts) rank FROM file_line_fts WHERE file_line_fts MATCH ? AND repo_id=? ORDER BY rank LIMIT 2600",(oq,self.repo_id)).fetchall()]
        except Exception: return [],{}
        ts=set(terms); ls={x.lower() for x in p.literals}; d={}
        for r,and_hit in rows:
            path=str(r["file_path"] or "")
            if not path or em.is_generated_path(path) or em._MINIFIED_FILE_RE.search(path) or em._VENDOR_PATH_RE.search(path): continue
            text=str(r["text"] or "").lower(); covered={x for x in ts if x in text}
            if not covered: continue
            x=d.setdefault(path,{"covered":set(),"hits":0,"and":False,"line":0.0,"multi":0,"literal":0,"rank":float(r["rank"] or 0)})
            x["covered"].update(covered); x["hits"]+=1; x["and"]|=and_hit; x["line"]=max(x["line"],len(covered)/max(1,len(ts))); x["multi"]+=int(len(covered)>=2); x["literal"]+=sum(1 for y in ls if y in text); x["rank"]=min(x["rank"],float(r["rank"] or 0))
        for path,x in d.items():
            fc=len(x["covered"])/max(1,len(ts)); rep=min(1.0,math.log1p(x["hits"])/math.log(13)); prox=min(1.0,x["line"]+.08*min(x["multi"],4)); lit=min(1.0,x["literal"]/max(1,len(ls))) if ls else 0
            conf=.44*fc+.26*prox+.12*rep+.10*float(x["and"])+.08*lit
            if not p.wants_tests and TEST.search(path): conf*=.78
            if not p.wants_aux and AUX.search(path): conf*=.68
            x["confidence"]=min(1.0,conf); x["fc"]=fc
        order=sorted(d,key=lambda z:(-d[z]["confidence"],-d[z]["fc"],-d[z]["line"],d[z]["rank"],z))
        return order[:128],{z:{"confidence":d[z]["confidence"]} for z in order}

    def structural(self: Any,p: Plan):
        if p.intent=="prose" or not p.anchors: return [],{}
        cache=self.__dict__.setdefault("_v7_usage_cache",{}); d={}
        for a in p.anchors[:4]:
            payload=cache.get(a)
            if payload is None:
                try: payload=self.find_references(query=a,group_by="none",snippet_lines=0,limit=48,auto_index=False,budget_tokens=16000)
                except Exception: payload={}
                cache[a]=payload
            pos=0
            for raw in walk_files(payload):
                path=str(raw.get("file_path") or raw.get("path") or "")
                if not path or em.is_generated_path(path): continue
                pos+=1; x=d.setdefault(path,{"anchors":set(),"hits":0,"rrf":0.0,"max":0.0}); x["anchors"].add(a.lower()); x["hits"]+=1; x["rrf"]+=1/(8+pos)
                try: x["max"]=max(x["max"],float(raw.get("confidence") or 0))
                except Exception: pass
        n=max(1,min(4,len(p.anchors)))
        for path,x in d.items():
            conf=.50*len(x["anchors"])/n+.22*min(1.0,math.log1p(x["hits"])/math.log(9))+.18*min(1.0,x["rrf"]*5)+.10*x["max"]
            if not p.wants_tests and TEST.search(path): conf*=.82
            if not p.wants_aux and AUX.search(path): conf*=.72
            x["confidence"]=min(1.0,conf)
        order=sorted(d,key=lambda z:(-d[z]["confidence"],-len(d[z]["anchors"]),-d[z]["max"],-d[z]["hits"],z))
        return order[:96],{z:{"confidence":d[z]["confidence"]} for z in order}

    def explore(self: Any,q: str,*args: Any,**kwargs: Any):
        self.__dict__.pop("_v7_zoekt",None); payload=original(self,q,*args,**kwargs)
        if not isinstance(payload,dict) or not isinstance(payload.get("files"),list) or not payload["files"]: return payload
        max_files=max(1,min(int(kwargs.get("max_files",6)),10)); entries={}; baseline=[]
        for e in payload["files"]:
            if isinstance(e,dict):
                path=str(e.get("path") or e.get("file_path") or "")
                if path and path not in entries: entries[path]=e; baseline.append(path)
        cap=self.__dict__.get("_v7_zoekt"); zoekt=list(cap[1]) if isinstance(cap,tuple) and cap and cap[0]==q else []
        p=parse(em,q); ex,exd=exact(self,p); an,and_=anchors(self,p); li,lid=lines(self,p); st,std=structural(self,p)
        channels={"baseline":baseline,"zoekt":zoekt,"exact":ex,"anchors":an,"line":li,"structural":st}
        rw={"definition":{"baseline":1,"zoekt":.9,"exact":1.4,"anchors":1,"line":.9,"structural":1.2},"symbol":{"baseline":1.1,"zoekt":1,"exact":1.3,"anchors":1,"line":.7,"structural":1},"code":{"baseline":.9,"zoekt":.9,"exact":.8,"anchors":1,"line":1.3,"structural":1.2},"prose":{"baseline":.8,"zoekt":.9,"exact":.2,"anchors":.3,"line":1.6,"structural":0}}[p.intent]
        cw={"definition":{"exact":1.15,"anchors":.5,"line":.7,"structural":.9},"symbol":{"exact":1,"anchors":.5,"line":.45,"structural":.75},"code":{"exact":.55,"anchors":.65,"line":1,"structural":.95},"prose":{"exact":.1,"anchors":.15,"line":1.25,"structural":0}}[p.intent]
        scores={}; ranks={}
        for name,files in channels.items():
            ranks[name]={x:i for i,x in enumerate(files,1)}
            for i,x in enumerate(files,1): scores[x]=scores.get(x,0)+rw[name]/(10+i)
        for x,d in exd.items(): scores[x]=scores.get(x,0)+cw["exact"]*d["confidence"]
        for x,d in and_.items(): scores[x]=scores.get(x,0)+cw["anchors"]*d["confidence"]
        for x,d in lid.items(): scores[x]=scores.get(x,0)+cw["line"]*d["confidence"]
        for x,d in std.items(): scores[x]=scores.get(x,0)+cw["structural"]*d["confidence"]
        tops={n:set(v[:32]) for n,v in channels.items()}; explicit={n.lower() for _k,n in p.definitions}; ids={x.lower() for x in p.identifiers}
        for path in list(scores):
            support=sum(path in s for s in tops.values()); scores[path]+=.075*max(0,support-1)+.035*len(ids & path_parts(path))
            km=set(exd.get(path,{}).get("kind_matches",())); scores[path]+=.85*len(explicit & km)
            if not p.wants_tests and TEST.search(path) and path not in entries: scores[path]*=.78
            if not p.wants_aux and AUX.search(path) and path not in entries: scores[path]*=.68
            if path.endswith(".pyi") and not re.search(r"\bpyi|stub\b",q,re.I): scores[path]*=.82
        order=sorted(scores,key=lambda x:(-scores[x],ranks["baseline"].get(x,9999),ranks["zoekt"].get(x,9999),x)); selected=[]; seen=set(); remaining=list(order)
        while remaining and len(selected)<max_files:
            if not selected or len(selected)>=3: choice=remaining[0]
            else: choice=max(remaining,key=lambda x:(scores[x]+.045*len({n for n,s in tops.items() if x in s}-seen),scores[x],x))
            selected.append(choice); seen.update(n for n,s in tops.items() if choice in s); remaining.remove(choice)
        result=dict(payload); result["files"]=[entries.get(x,{"path":x,"language":"unknown","symbols":[],"source_sections":[]}) for x in selected]; result["experiment"]={"name":"generic_structural_hybrid_v7","intent":p.intent}
        diag({"repo":str(getattr(self,"repo_id","")),"query":q,"plan":{"intent":p.intent,"identifiers":p.identifiers,"anchors":p.anchors,"terms":p.terms},"channels":{n:v[:40] for n,v in channels.items()},"final":selected,"scores":{x:round(scores[x],6) for x in selected}})
        return result

    cls._zoekt_candidate_files=capture; cls.tool_explore=explore; cls._structural_hybrid_experiment_installed=True

install()
