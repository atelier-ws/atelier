"""Diagnose the django-14376 'passwd OR kwargs' row that loses gold."""
import json

ROOT = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch"
gold = json.load(open(f"{ROOT}/gold.json"))
rows = [json.loads(line) for line in open(f"{ROOT}/corpus.jsonl") if line.strip()]
cs = [r for r in rows if r["tool"] == "code_search" and r["result"] is not None]
r = next(x for x in cs if x["task"] == "django__django-14376" and "settings_dict" in json.dumps(x["input"]))
res = r["result"]
print("query:", r["input"])
print("GOLD:", gold.get("django__django-14376"))
print("exact_match:", res.get("exact_match"), "keys:", sorted(res.keys()))
eps = sorted(res.get("entry_points") or [], key=lambda e: -(e.get("score") or 0))
print(f"entry_points: {len(eps)}")
for e in eps[:12]:
    print(f"   score={e.get('score'):>10.2f}  {e.get('qualified_name')}  @ {e.get('path')}:{e.get('line')}")
print("files (with sections):")
for f in res.get("files") or []:
    secs = f.get("source_sections") or []
    flag = " <== GOLD" if f.get("path") in gold.get("django__django-14376", []) else ""
    print(f"   {f.get('path')} sections={len(secs)}{flag}")
    for s in secs:
        print(f"      matched={s.get('matched')} line={s.get('line')} qn={s.get('qualified_name')} clen={len(s.get('content',''))}")
print("any mysql/base.py in entry_points?", any('mysql/base.py' in (e.get('path') or '') for e in eps))
print("any mysql/base.py in files?", any('mysql/base.py' in (f.get('path') or '') for f in res.get('files') or []))
