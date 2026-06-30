"""codebase-memory-mcp (CMM) retrieval MRR eval on the def/content golds.

New external-provider retrieval arm for DeusData's ``codebase-memory-mcp`` --
a single static Go binary that indexes a repo into a persistent knowledge graph
(BM25 full-text + bundled nomic-embed-code semantic edges, all local, no network).
See https://deusdata.github.io/codebase-memory-mcp/ .

Methodology mirrors ``eval_cg_mrr.py`` / ``fitness_explore_mrr.py`` exactly so the
arm is apples-to-apples with the lexical / +zoekt / BGE-semantic channels:
iterate the SAME (query, tid, prefix) pairs, run the tool once per unique query,
score each pair independently by rank-of-gold-file (endswith match, top-10).

Two CMM tools back the two golds (same split the other external arms use):
  * definition gold  <- ``search_graph`` (graph FTS; result key ``file_path``)
  * content gold     <- ``search_code``  (grep + graph enrich; result key ``file``)

The binary is invoked in one-shot ``cli <tool> '<json>'`` mode (no MCP stdio
handshake needed -- the same graph.db is read every call). All CMM state is kept
under an isolated ``$HOME`` (``CMM_HOME``) so a run never touches a user's cache.

Provisioning:
  Set ``CMM_BIN`` to the ``codebase-memory-mcp`` binary, or let the harness fetch
  the pinned Linux release into ``CMM_HOME/bin`` on first use. Each repo is indexed
  once (idempotent: CMM re-parses only changed files).

Environment variables (same family as eval_cg_mrr / fitness_explore_mrr):
  FITNESS_PAIRS   pairs JSON, comma-sep (default benchmarks/codebench/data/bench_pairs_def_gold.json)
  FITNESS_SAMPLE  cap total unique queries across all repos (0 = all)
  FITNESS_REPO    substring filter on repo prefix
  CMM_BIN         path to the codebase-memory-mcp binary (skips download)
  CMM_HOME        isolated state/cache dir (default /tmp/cmm-bench)

Emits one JSON line: {mrr, hit1, hit3, n, latency_ms, by_repo, golds}.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

SAMPLE = int(os.environ.get("FITNESS_SAMPLE", "0"))
REPO_FILTER = os.environ.get("FITNESS_REPO", "")
CMM_HOME = Path(os.environ.get("CMM_HOME", "/tmp/cmm-bench")).resolve()

# Pinned release -- a single static binary with the embedder compiled in.
_CMM_VERSION = "v0.8.1"
_CMM_ASSET = "codebase-memory-mcp-linux-amd64.tar.gz"
_CMM_URL = f"https://github.com/DeusData/codebase-memory-mcp/releases/download/{_CMM_VERSION}/{_CMM_ASSET}"

_gold_paths = [
    p.strip()
    for p in os.environ.get("FITNESS_PAIRS", "benchmarks/codebench/data/bench_pairs_def_gold.json").split(",")
    if p.strip()
]
_golds: list[tuple[str, list, dict]] = []
repos: dict | None = None
for _gp in _gold_paths:
    with open(_gp) as _f:
        _d = json.load(_f)
    if repos is None:
        repos = _d["repos"]
    _golds.append((_d.get("gold_kind", "definition"), _d["pairs"], _d["true_map"]))
assert repos is not None
pairs = [row for _k, _p, _tm in _golds for row in _p]
# Which CMM tool / result-key backs each gold kind.
_TOOL_FOR = {
    "definition": ("search_graph", "file_path"),
    "content": ("search_code", "file"),
    "swebench": ("search_code", "file"),  # mixed grep/text queries → content search
}


def norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def rank_of_true(files: list, true_files: list[str]) -> int | None:
    """1-indexed rank of the first gold file (endswith match), or None."""
    tn = [norm(t) for t in true_files]
    for i, f in enumerate(files, 1):
        nf = norm(f)
        if any(nf.endswith(t) or t.endswith(nf) for t in tn):
            return i
    return None


def ensure_binary() -> Path:
    """Return the codebase-memory-mcp binary path, downloading the pinned release if needed."""
    env_bin = os.environ.get("CMM_BIN")
    if env_bin and Path(env_bin).is_file():
        return Path(env_bin)
    bindir = CMM_HOME / "bin"
    binpath = bindir / "codebase-memory-mcp"
    if binpath.is_file():
        return binpath
    bindir.mkdir(parents=True, exist_ok=True)
    tgz = bindir / _CMM_ASSET
    print(f"[cmm] downloading {_CMM_URL}", file=sys.stderr, flush=True)
    urllib.request.urlretrieve(_CMM_URL, tgz)  # pinned github release asset
    with tarfile.open(tgz) as tf:
        tf.extract("codebase-memory-mcp", path=bindir)  # nosec - pinned asset
    binpath.chmod(0o755)
    return binpath


def _cli(binp: Path, tool: str, args: dict, env: dict, timeout: int = 300) -> dict:
    """Run ``codebase-memory-mcp cli <tool> '<json>'`` and return the parsed JSON object."""
    proc = subprocess.run(
        [str(binp), "cli", tool, json.dumps(args)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    out = proc.stdout.strip()
    if not out:
        return {}
    # The cli prints a single JSON object on stdout (logs go to stderr).
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}


def _paths(result: dict, key: str, limit: int = 10) -> list[str]:
    """Ranked, de-duplicated repo-relative file paths from a CMM search result."""
    files: list[str] = []
    seen: set[str] = set()
    for it in result.get("results", []) or []:
        f = norm(str(it.get(key) or it.get("file_path") or it.get("file") or ""))
        if f and f not in seen:
            seen.add(f)
            files.append(f)
        if len(files) >= limit:
            break
    return files


# ---------------------------------------------------------------------------
# Query set (same sampling / filter knobs as eval_cg_mrr.py)
# ---------------------------------------------------------------------------
uq: dict[str, set[str]] = {}
for q, _tid, prefix in pairs:
    uq.setdefault(prefix, set()).add(q)
if REPO_FILTER:
    uq = {p: qs for p, qs in uq.items() if REPO_FILTER in p}
if SAMPLE:
    n_repos = max(len(uq), 1)
    per_repo = max(1, SAMPLE // n_repos)
    uq = {p: sorted(qs)[:per_repo] for p, qs in uq.items()}
runset = {p: set(qs) for p, qs in uq.items()}
total_unique = sum(len(qs) for qs in uq.values())
print(f"[cmm] {total_unique} unique queries across {len(uq)} repos", file=sys.stderr, flush=True)

binp = ensure_binary()
env = dict(os.environ)
env["HOME"] = str(CMM_HOME / "home")
(CMM_HOME / "home").mkdir(parents=True, exist_ok=True)

# {(prefix, query): {gold_kind: ranked_files}}
filecache: dict[tuple[str, str], dict[str, list[str]]] = {}
latencies: list[float] = []
done = 0
t0 = time.time()

for prefix, queries in sorted(uq.items()):
    meta = repos[prefix]
    ws = meta["ws"]
    if not Path(ws).is_dir():
        print(f"[cmm] skip {prefix}: ws not found ({ws})", file=sys.stderr)
        continue
    # Index (idempotent: CMM re-parses only changed files; re-runs are seconds).
    # CMM derives the project name from the ABSOLUTE path -- never guess it; take
    # the authoritative name back from the index_repository result.
    print(f"[cmm] index {prefix} ...", file=sys.stderr, flush=True)
    t1 = time.time()
    idx = _cli(binp, "index_repository", {"repo_path": ws, "mode": "full"}, env, timeout=3600)
    project = idx.get("project")
    if not project or (idx.get("status") != "indexed" and not idx.get("nodes")):
        print(f"[cmm] index FAILED for {prefix}: {json.dumps(idx)[:400]}", file=sys.stderr)
        continue
    print(
        f"[cmm] index {prefix} done in {time.time() - t1:.1f}s nodes={idx.get('nodes')} project={project}",
        file=sys.stderr,
        flush=True,
    )
    for query in sorted(queries):
        ranked: dict[str, list[str]] = {}
        t1 = time.time()
        for tool, key in {_TOOL_FOR[k][0]: _TOOL_FOR[k][1] for k, _p, _t in _golds}.items():
            if tool == "search_graph":
                res = _cli(binp, tool, {"project": project, "query": query, "limit": 10}, env, timeout=120)
            else:  # search_code
                res = _cli(
                    binp,
                    tool,
                    {"project": project, "pattern": query, "limit": 10, "mode": "compact"},
                    env,
                    timeout=120,
                )
            ranked[tool] = _paths(res, key)
        _q_lat = (time.time() - t1) * 1000
        latencies.append(_q_lat)
        filecache[(prefix, query)] = ranked
        done += 1
        if done % 50 == 0 or done == total_unique:
            el = time.time() - t0
            rate = done / el if el else 0
            print(
                f"[cmm] queries {done}/{total_unique} elapsed={el:.0f}s rate={rate:.1f}/s",
                file=sys.stderr,
                flush=True,
            )


def _pct(vals: list[float], p: int) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int((p / 100.0) * (len(s) - 1)))]


def _score_gold(kind: str, gpairs, gtm) -> dict:
    tool = _TOOL_FOR.get(kind, ("search_graph", "file_path"))[0]
    agg = {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}
    by_repo: dict[str, dict] = {}
    for q, tid, prefix in gpairs:
        if q not in runset.get(prefix, set()):
            continue
        trues = [p.replace("\\", "/") for p in gtm.get(tid, []) if p]
        if not trues:
            continue
        ranked = filecache.get((prefix, q), {})
        r = rank_of_true(ranked.get(tool, []), trues)
        br = by_repo.setdefault(prefix, {"rr": 0.0, "h1": 0, "h3": 0, "n": 0})
        for d in (agg, br):
            d["n"] += 1
            if r is not None:
                d["rr"] += 1.0 / r
                if r == 1:
                    d["h1"] += 1
                if r <= 3:
                    d["h3"] += 1
    return {
        "mrr": round(agg["rr"] / max(agg["n"], 1), 4),
        "hit1": round(agg["h1"] / max(agg["n"], 1), 4),
        "hit3": round(agg["h3"] / max(agg["n"], 1), 4),
        "n": agg["n"],
        "by_repo": {p: {"mrr": round(d["rr"] / max(d["n"], 1), 4), "n": d["n"]} for p, d in sorted(by_repo.items())},
    }


_lat = {
    "mean": round(sum(latencies) / max(len(latencies), 1), 1),
    "p50": round(_pct(latencies, 50), 1),
    "p95": round(_pct(latencies, 95), 1),
    "max": round(max(latencies), 1) if latencies else 0,
    "over_100ms": sum(1 for x in latencies if x > 100.0),
}
_gold_scores = {kind: _score_gold(kind, gp, gtm) for kind, gp, gtm in _golds}
# Collect per-repo latencies from filecache (same order as query loop).
_lat_by_repo: dict[str, list[float]] = {}
_lat_idx = 0
for prefix, queries in sorted(uq.items()):
    for _ in sorted(queries):
        if _lat_idx < len(latencies):
            _lat_by_repo.setdefault(prefix, []).append(latencies[_lat_idx])
            _lat_idx += 1
out = {**_gold_scores[_golds[0][0]], "latency_ms": _lat, "golds": _gold_scores, "provider": "cmm", "mode": "ext[cmm]"}
print(json.dumps(out))

# ── Summary (matches eval_external_provider_mrr.py format) ──
print("\n" + "─" * 60, file=sys.stderr)
print("  provider=cmm", file=sys.stderr)
for _gk, _gd in _gold_scores.items():
    print(f"  gold={_gk:<18} MRR {_gd['mrr']:.4f}  hit@1 {_gd['hit1']:.4f}  n={_gd['n']}", file=sys.stderr)
print(f"  lat  mean={_lat['mean']:.0f}ms  p95={_lat['p95']:.0f}ms  max={_lat['max']:.0f}ms", file=sys.stderr)
_primary_gk = _golds[0][0]
for _rprefix, _rd in sorted(_gold_scores[_primary_gk].get("by_repo", {}).items(), key=lambda kv: kv[1].get("mrr", 0)):
    _rmrr = _rd.get("mrr", 0)
    _rn = _rd.get("n", 0)
    _icon = "✓" if _rmrr >= 0.9 else ("~" if _rmrr >= 0.5 else "✗")
    _short = _rprefix.split("__")[-1] if "__" in _rprefix else _rprefix
    _mrr_parts = []
    for _gk in ("definition", "content", "swebench"):
        _gk_repo = (_gold_scores.get(_gk) or {}).get("by_repo", {}).get(_rprefix)
        if _gk_repo and isinstance(_gk_repo, dict):
            _mrr_parts.append(f"{_gk_repo['mrr']:.3f}")
    _mrr_str = "/".join(_mrr_parts) if len(_mrr_parts) > 1 else f"{_rmrr:.3f}"
    _rlat = _lat_by_repo.get(_rprefix, [])
    _rp95 = _pct(_rlat, 95)
    _rp100 = max(_rlat) if _rlat else 0
    print(f"  {_icon}  {_short:<22} n={_rn:<4} MRR={_mrr_str}  p95={_rp95:.0f}ms  p100={_rp100:.0f}ms", file=sys.stderr)
print("─" * 60 + "\n", file=sys.stderr)
