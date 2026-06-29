"""Prepare per-repo embedding finetune data for ONE repo (atelier first).

Honest split for measuring finetune lift on real queries:
  * train.jsonl  = SYNTHETIC queries mined from the repo source
                   (synthetic_pair_miner.py) -- query-distinct from the bench.
  * test.jsonl   = REAL bench queries for the repo (bench_pairs_def_gold.json).
  * corpus.jsonl = union of all gold files (real + synthetic) so eval MRR ranks
                   the gold file against a realistic corpus, not just test golds.

Gold-file overlap between train and test is expected and fine: the model learns
good file representations; the eval QUERIES are never seen in training.

Formats match train_embedding.py:
  train.jsonl  {"query", "positive"}
  test.jsonl   {"query", "positive", "gold_path", "tid"}
  corpus.jsonl {"id": rel_path, "text": "Path: rel_path\\n<content>"}

Usage:
  uv run --no-sync python benchmarks/embedding/prep_atelier_embed.py \
      --prefix atelier__atelier --repo-dir . --syn-pairs /tmp/atelier_syn.json \
      --out-dir /tmp/atelier_embed_data
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def read_content(repo_dir: Path, rel: str, max_chars: int) -> str | None:
    try:
        text = (repo_dir / rel).read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, IsADirectoryError, OSError):
        return None
    return text[:max_chars] + "\n# ... (truncated)" if len(text) > max_chars else text


def pairs_for_prefix(bench: dict, prefix: str) -> tuple[list[tuple[str, str]], dict[str, list[str]]]:
    pairs = [(q, tid) for q, tid, p in bench["pairs"] if p == prefix]
    tids = {tid for _, tid in pairs}
    true_map = {t: bench["true_map"][t] for t in tids if t in bench["true_map"]}
    return pairs, true_map


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="atelier__atelier")
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--real-pairs", default="benchmarks/codebench/data/bench_pairs_def_gold.json")
    ap.add_argument("--syn-pairs", default="/tmp/atelier_syn.json")
    ap.add_argument("--out-dir", default="/tmp/atelier_embed_data")
    ap.add_argument("--max-chars", type=int, default=1500)
    args = ap.parse_args()

    repo_dir = Path(args.repo_dir)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(args.real_pairs) as fh:
        real = json.load(fh)
    with open(args.syn_pairs) as fh:
        syn = json.load(fh)
    real_pairs, real_tm = pairs_for_prefix(real, args.prefix)
    syn_pairs = [(q, tid) for q, tid, _ in syn["pairs"]]
    syn_tm = syn["true_map"]

    # Union corpus: every gold file referenced by real or synthetic pairs.
    gold_files: set[str] = set()
    for tm in (real_tm, syn_tm):
        for paths in tm.values():
            gold_files.update(paths)
    corpus: dict[str, str] = {}
    for rel in sorted(gold_files):
        c = read_content(repo_dir, rel, args.max_chars)
        if c:
            corpus[rel] = c
    print(f"[prep] corpus: {len(corpus)}/{len(gold_files)} gold files readable", file=sys.stderr)

    def first_gold(tm: dict[str, list[str]], tid: str) -> str | None:
        for p in tm.get(tid, []):
            if p in corpus:
                return p
        return None

    # train = synthetic
    n_train = n_skip = 0
    with open(out / "train.jsonl", "w") as f:
        for q, tid in syn_pairs:
            gp = first_gold(syn_tm, tid)
            if not gp:
                n_skip += 1
                continue
            f.write(json.dumps({"query": q, "positive": corpus[gp]}) + "\n")
            n_train += 1

    # test = real
    n_test = 0
    with open(out / "test.jsonl", "w") as f:
        for q, tid in real_pairs:
            gp = first_gold(real_tm, tid)
            if not gp:
                continue
            f.write(json.dumps({"query": q, "positive": corpus[gp], "gold_path": gp, "tid": tid}) + "\n")
            n_test += 1

    with open(out / "corpus.jsonl", "w") as f:
        for rel, content in corpus.items():
            f.write(json.dumps({"id": rel, "text": f"Path: {rel}\n{content}"}) + "\n")

    meta = {
        "prefix": args.prefix,
        "num_train": n_train,
        "num_test": n_test,
        "num_corpus": len(corpus),
        "train_skipped_no_content": n_skip,
        "max_chars": args.max_chars,
    }
    with open(out / "meta.json", "w") as fh:
        json.dump(meta, fh, indent=2)
    print(json.dumps(meta), file=sys.stderr)
    print(f"[prep] wrote {out}/train.jsonl test.jsonl corpus.jsonl", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
