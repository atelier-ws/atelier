"""Parity check: run the PRODUCTION _lean_code_search_view over the real corpus."""

import json

from atelier.gateway.adapters.mcp_server import _lean_code_search_view

ROOT = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch"


def ser(o):
    return json.dumps(o, separators=(",", ":"))


def gold_hit(text, gold_files):
    return any(g in text for g in (gold_files or []) if g != "uv.lock")


def main():
    gold = json.load(open(f"{ROOT}/gold.json"))
    rows = [json.loads(line) for line in open(f"{ROOT}/corpus.jsonl") if line.strip()]
    cs = [r for r in rows if r["tool"] == "code_search" and r["result"] is not None]
    to = tl = gok = ngold = 0
    for r in cs:
        inp = r["input"] if isinstance(r["input"], dict) else {}
        mf = inp.get("max_files", 8)
        raw = inp.get("paths") or inp.get("path")
        if isinstance(raw, str):
            seeds = [p.strip() for p in raw.split(",") if p.strip()]
        elif isinstance(raw, list):
            seeds = [p for p in raw if p]
        else:
            seeds = None
        lean = _lean_code_search_view(r["result"], max_files=mf, seed_files=seeds)
        leant = ser(lean)
        gf = gold.get(r["task"], [])
        if gold_hit(ser(r["result"]), gf):
            ngold += 1
            if gold_hit(leant, gf):
                gok += 1
        to += r["result_chars"]
        tl += len(leant)
    print(f"PRODUCTION helper over {len(cs)} real code_search calls:")
    print(f"  orig={to:,}  lean={tl:,}  reduction={100 * (1 - tl / to):.0f}%")
    print(f"  gold retained: {gok}/{ngold}")


if __name__ == "__main__":
    main()
