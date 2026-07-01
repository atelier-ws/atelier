#!/usr/bin/env python3
"""Build an EMBEDDER-INDEPENDENT semantic retrieval gold from git history.

Query = a commit's subject line (real developer intent, natural language).
Target = the single source file that commit changed.

Unlike bench_pairs_semantic_gold.json (mined by "embedder X ranks it <=5", which
is circular for X and biased against every other model), this gold references NO
embedder and NO retrieval rank -- so it measures any embedder fairly. Only
single-source-file commits with a descriptive subject are kept, giving an
unambiguous 1:1 (query -> file) label.

Usage:
    uv run python benchmarks/codebench/build_commit_gold.py \
        --out benchmarks/codebench/data/bench_pairs_commit_gold.json \
        --per-repo 60 --scan 4000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys

# Conventional-commit / project prefixes to strip from the subject so the query
# reads like a plain description, not a changelog tag.
_PREFIX = re.compile(
    r"^\s*(?:\[[^\]]+\]\s*)?(?:[A-Z]{2,5}|fix|feat|bug|enh|perf|refactor|test|tests|doc|docs|maint|build|ci|chore|style|revert)\s*[:\-]\s*",
    re.I,
)
_TICKET = re.compile(r"\b(?:gh-|#|pr\s*#?|issue\s*#?)\d+\b", re.I)
_SKIP = re.compile(
    r"\b(?:merge|revert|bump|version|release|changelog|typo|whitespace|lint|black|isort|pre-commit|rename|deprecat|backport|cherry|wip)\b",
    re.I,
)


def clean_subject(s: str) -> str:
    s = _PREFIX.sub("", s.strip())
    s = _TICKET.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" .;:-")
    return s


def mine_repo(ws: str, scan: int, cap: int) -> list[tuple[str, str]]:
    """Return [(query, rel_file)] for single-.py-file commits with a clean subject."""
    out: list[tuple[str, str]] = []
    seen_files: set[str] = set()
    fmt = "%x01%s"  # SOH + subject; --name-only lists files after
    try:
        log = subprocess.check_output(
            ["git", "-C", ws, "log", "--no-merges", f"-n{scan}", "--name-only", f"--pretty=format:{fmt}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return out
    # split into commit blocks on the SOH marker
    for block in log.split("\x01"):
        block = block.strip("\n")
        if not block:
            continue
        lines = block.split("\n")
        subject = lines[0].strip()
        files = [ln.strip() for ln in lines[1:] if ln.strip()]
        py = [
            f for f in files if f.endswith(".py") and "/tests/" not in f and not os.path.basename(f).startswith("test_")
        ]
        if len(py) != 1:  # exactly one non-test source file -> unambiguous label
            continue
        rel = py[0]
        if rel in seen_files:  # one query per file (avoid over-weighting churny files)
            continue
        if _SKIP.search(subject):
            continue
        q = clean_subject(subject)
        if len(q.split()) < 5 or len(q) < 20:  # descriptive only
            continue
        if not os.path.isfile(os.path.join(ws, rel)):  # still exists at HEAD -> retrievable
            continue
        out.append((q, rel))
        seen_files.add(rel)
        if len(out) >= cap:
            break
    return out


def _tok(s: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", s.lower()) if len(w) >= 3}


def mine_docstrings(db_path: str, cap: int) -> list[tuple[str, str]]:
    """Return [(query, rel_file)] from symbol docstrings. Embedder-independent:
    the query is the docstring's first sentence, the target is its file. Filters
    out docstrings that merely restate the symbol name (trivially lexical) and
    param/return-only stubs."""
    out: list[tuple[str, str]] = []
    seen_files: set[str] = set()
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT symbol_name, doc_summary, file_path FROM symbols "
            "WHERE doc_summary IS NOT NULL AND length(doc_summary) > 40 "
            "AND kind IN ('function','class','method') ORDER BY length(doc_summary) DESC"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return out
    for name, doc, fp in rows:
        if "/tests/" in fp or os.path.basename(fp).startswith("test_"):
            continue
        if fp in seen_files:
            continue
        # first sentence, cleaned
        q = re.split(r"(?<=[.!?])\s", str(doc).strip())[0].strip()
        q = re.sub(r"\s+", " ", q).strip(" .;:-")
        if len(q.split()) < 6 or len(q) < 30:
            continue
        if q.lower().startswith((":param", ":return", "param ", "returns ", "return ", "args:", "todo")):
            continue
        # skip if the query is basically the symbol name tokens (trivially lexical)
        if _tok(q) and _tok(q) <= (_tok(name) | {"the", "a", "an", "of", "for", "to", "is", "and"}):
            continue
        out.append((q, fp))
        seen_files.add(fp)
        if len(out) >= cap:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="benchmarks/codebench/data/bench_pairs_commit_gold.json")
    ap.add_argument("--repos-from", default="benchmarks/codebench/data/bench_pairs_def_gold.json")
    ap.add_argument("--per-repo", type=int, default=60)
    ap.add_argument("--scan", type=int, default=4000, help="commits to scan per repo")
    ap.add_argument("--min-commits", type=int, default=100, help="skip shallow clones")
    args = ap.parse_args()
    repos = json.load(open(args.repos_from))["repos"]
    pairs, true_map, out_repos = [], {}, {}
    n_commit = n_doc = 0
    for pfx, m in repos.items():
        ws = m.get("ws", "")
        db = m.get("db")
        got: list[tuple[str, str, str]] = []  # (query, rel, source)
        # commit-message source (needs real git history)
        if os.path.isdir(os.path.join(ws, ".git")):
            try:
                nc = int(
                    subprocess.check_output(
                        ["git", "-C", ws, "rev-list", "--count", "HEAD"], text=True, stderr=subprocess.DEVNULL
                    ).strip()
                )
            except Exception:
                nc = 0
            if nc >= args.min_commits:
                got += [(q, rel, "commit") for q, rel in mine_repo(ws, args.scan, args.per_repo)]
        # docstring source (all repos, from the index)
        if db and os.path.isfile(db):
            got += [(q, rel, "doc") for q, rel in mine_docstrings(db, args.per_repo)]
        if not got:
            print(f"[semgold] skip {pfx} (no history + no db)", file=sys.stderr)
            continue
        seen = set()
        nc_r = nd_r = 0
        for q, rel, src in got:
            if (q, rel) in seen:
                continue
            seen.add((q, rel))
            tid = f"{src}-" + hashlib.sha1(f"{pfx}:{rel}:{q}".encode()).hexdigest()[:12]
            pairs.append([q, tid, pfx])
            true_map[tid] = [rel]
            if src == "commit":
                nc_r += 1
                n_commit += 1
            else:
                nd_r += 1
                n_doc += 1
        out_repos[pfx] = m
        print(f"[semgold] {pfx:26} commit={nc_r:3d} doc={nd_r:3d}", file=sys.stderr)
    json.dump(
        {"gold_kind": "semantic_indep", "pairs": pairs, "true_map": true_map, "repos": out_repos},
        open(args.out, "w"),
        indent=1,
    )
    print(
        f"[semgold] wrote {len(pairs)} pairs ({n_commit} commit + {n_doc} docstring) across {len(out_repos)} repos -> {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
