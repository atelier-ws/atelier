"""Generate a human-readable comparison report between baseline and Atelier runs.

Reads:
  - baseline_preds.json  — patches from uncompressed run
  - atelier_preds.json   — patches from Atelier-compressed run
  - proxy_savings.jsonl  — per-request token savings logged by atelier_proxy.py

Outputs a Markdown report + prints a compact summary to stdout.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

from atelier.gateway.cli.progress import ProgressReporter


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def load_preds(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {k: v.get("model_patch", "") for k, v in data.items()}


def report(baseline_path: Path, atelier_path: Path, savings_log: Path, output: Path) -> None:
    progress = ProgressReporter("swe", total=4)
    progress.start("building report", current="load predictions")
    baseline = load_preds(baseline_path)
    atelier = load_preds(atelier_path)
    progress.step("building report", current="load savings log")
    savings = load_jsonl(savings_log)
    progress.step("building report", current="compute metrics")

    all_ids = sorted(set(baseline) | set(atelier))
    n_baseline_patched = sum(1 for p in baseline.values() if p)
    n_atelier_patched = sum(1 for p in atelier.values() if p)

    # Patch similarity (identical / non-empty)
    identical = sum(1 for iid in all_ids if baseline.get(iid) and baseline.get(iid) == atelier.get(iid))
    both_patched = sum(1 for iid in all_ids if baseline.get(iid) and atelier.get(iid))

    # Token savings from proxy log
    total_before = sum(e["before_tokens"] for e in savings)
    total_after = sum(e["after_tokens"] for e in savings)
    total_saved = total_before - total_after
    pct_saved = 100 * total_saved / max(1, total_before)
    per_req = [e["pct"] for e in savings]
    avg_pct = mean(per_req) if per_req else 0.0
    n_reqs = len(savings)
    progress.step("building report", current="write markdown")

    lines = [
        "# Atelier x SWE-bench Lite — Evaluation Report",
        "",
        "## Patch Coverage",
        "| Run | Instances | With Patch |",
        "|-----|-----------|------------|",
        f"| Baseline (no compression) | {len(baseline)} | {n_baseline_patched} |",
        f"| Atelier (compressed) | {len(atelier)} | {n_atelier_patched} |",
        "",
        "## Patch Similarity",
        f"- Instances with patches in **both** runs: {both_patched}",
        f"- **Identical patches**: {identical} / {both_patched}"
        + (f" ({100 * identical // max(1, both_patched)}%)" if both_patched else ""),
        "",
        "## Token Savings (Atelier proxy log)",
        "| Metric | Value |",
        "|--------|-------|",
        f"| LLM requests intercepted | {n_reqs} |",
        f"| Tokens before compression | {total_before:,} |",
        f"| Tokens after compression | {total_after:,} |",
        f"| Tokens saved | {total_saved:,} |",
        f"| Overall reduction | **{pct_saved:.1f}%** |",
        f"| Avg per-request reduction | {avg_pct:.1f}% |",
        "",
        "## Next Steps",
        "Submit both prediction files to sb-cli to get official % resolved:",
        "```bash",
        f"sb-cli submit swe-bench_lite dev --predictions_path {baseline_path} --run_id atelier-baseline",
        f"sb-cli submit swe-bench_lite dev --predictions_path {atelier_path} --run_id atelier-compressed",
        "```",
        "Then compare % resolved. If equal, the compression is lossless at this scale.",
    ]

    md = "\n".join(lines)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md)
    progress.step("building report", current=output.name)
    progress.finish("report complete")

    # stdout summary
    print("\n" + "=" * 60)
    print("ATELIER x SWE-BENCH REPORT")
    print("=" * 60)
    print(f"  Instances         : {len(all_ids)}")
    print(f"  Baseline patches  : {n_baseline_patched}")
    print(f"  Atelier patches   : {n_atelier_patched}")
    print(f"  Identical patches : {identical}/{both_patched}")
    print(f"  Token savings     : {pct_saved:.1f}%  ({total_saved:,} tokens)")
    print(f"  Proxy requests    : {n_reqs}")
    print(f"  Report written    : {output}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--atelier", required=True)
    parser.add_argument("--savings-log", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report(
        Path(args.baseline),
        Path(args.atelier),
        Path(args.savings_log),
        Path(args.output),
    )


if __name__ == "__main__":
    main()
