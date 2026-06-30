"""External provider MRR benchmark.

Channels: ctags / ast-grep / serena / code-index-mcp / jcodemunch
Same gold set and output JSON format as fitness_explore_mrr.py.

Run via:
    atelier eval retrieval --channel ctags
    atelier eval retrieval --channel ctags --channel lexical  # comparison table
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

# ---------------------------------------------------------------------------
# Minimal JSON-RPC line client (used by JCodeMunchProvider)
# ---------------------------------------------------------------------------


class _JsonRpcLineClient:
    def __init__(self, command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
        self.command = command
        self.cwd = cwd
        self.env = env
        self.proc: subprocess.Popen[str] | None = None
        self._next_id = 1

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.command,
            cwd=str(self.cwd) if self.cwd else None,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.call("initialize", {"protocolVersion": "2024-11-05", "clientInfo": {"name": "atelier-bench", "version": "1"}, "capabilities": {}})
        self.notify("notifications/initialized", {})

    def _read_message(self, *, timeout: float) -> dict[str, Any]:
        assert self.proc is not None and self.proc.stdout is not None
        proc = self.proc
        timed_out = threading.Event()

        def _kill_on_timeout() -> None:
            timed_out.set()
            with contextlib.suppress(Exception):
                proc.kill()

        timer = threading.Timer(timeout, _kill_on_timeout)
        timer.start()
        try:
            line = proc.stdout.readline()
        finally:
            timer.cancel()
        if timed_out.is_set() or not line:
            stderr = ""
            with contextlib.suppress(Exception):
                if proc.stderr is not None:
                    stderr = proc.stderr.read(2000)
            raise TimeoutError(f"timed out waiting for JSON-RPC response: {stderr[:400]}")
        return cast(dict[str, Any], json.loads(line))

    def notify(self, method: str, params: dict[str, Any]) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def call(self, method: str, params: dict[str, Any], *, timeout: float = 60) -> dict[str, Any]:
        assert self.proc is not None and self.proc.stdin is not None
        request_id = self._next_id
        self._next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        while True:
            message = self._read_message(timeout=timeout)
            if message.get("id") != request_id:
                continue
            return message

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.proc.wait(timeout=6)
        self.proc.kill()

sys.path.insert(0, "src")
sys.path.insert(0, ".")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
_parser = argparse.ArgumentParser(description="External provider MRR benchmark")
_parser.add_argument(
    "--provider",
    required=True,
    choices=["ctags", "ast-grep", "serena", "code-index-mcp", "jcodemunch", "cg", "rg"],
)
_parser.add_argument("--full", action="store_true")
_parser.add_argument("--sample", type=int, default=None)
_parser.add_argument("--repo", default=os.environ.get("FITNESS_REPO", ""))
_args, _ = _parser.parse_known_args()

PROVIDER = _args.provider
_TAG = f"[ext:{PROVIDER}]"  # per-provider tag so parallel runs don't interleave identically
FULL = _args.full
SAMPLE = _args.sample
REPO_FILTER = _args.repo

# ---------------------------------------------------------------------------
# Gold loading
# ---------------------------------------------------------------------------
FITNESS_PAIRS = os.environ.get(
    "FITNESS_PAIRS",
    "benchmarks/codebench/data/bench_pairs_def_gold.json",
)
_gold_paths = [Path(p.strip()) for p in FITNESS_PAIRS.split(",") if p.strip()]

_golds: list[tuple[str, list, dict]] = []  # [(kind, pairs, true_map)]
_all_repos: dict[str, dict] = {}  # prefix -> {ws, db, ...}

for _gp in _gold_paths:
    _raw = json.loads(_gp.read_text())
    _kind = _raw.get("gold_kind", "definition")
    _golds.append((_kind, _raw["pairs"], _raw["true_map"]))
    for _prefix, _meta in _raw.get("repos", {}).items():
        if _prefix not in _all_repos:
            _all_repos[_prefix] = _meta

# Build (query, prefix) -> {kind: tid} lookup for scoring
_q_to_tids: dict[tuple[str, str], dict[str, str]] = {}
for _kind, _pairs, _tm in _golds:
    for _q, _tid, _prefix in _pairs:
        _key = (_q, _prefix)
        if _key not in _q_to_tids:
            _q_to_tids[_key] = {}
        _q_to_tids[_key][_kind] = _tid

# Union of unique (query, prefix) pairs
_union: list[tuple[str, str]] = []  # [(query, prefix)]
_seen: set[tuple[str, str]] = set()
for _, _pairs, _ in _golds:
    for _q, _tid, _prefix in _pairs:
        if (_q, _prefix) not in _seen:
            _seen.add((_q, _prefix))
            _union.append((_q, _prefix))

if REPO_FILTER:
    _union = [(q, p) for q, p in _union if REPO_FILTER in p]
    _all_repos = {k: v for k, v in _all_repos.items() if REPO_FILTER in k}

# Sample
if not FULL:
    cap = SAMPLE if SAMPLE else 500
    _by_repo: dict[str, list] = defaultdict(list)
    for item in _union:
        _by_repo[item[1]].append(item)
    per_repo = max(1, cap // max(len(_by_repo), 1))
    _union = [x for items in _by_repo.values() for x in items[:per_repo]]

# Group by repo
_queries_by_repo: dict[str, list[str]] = defaultdict(list)
_seen_qr: set[tuple[str, str]] = set()
for q, prefix in _union:
    if (q, prefix) not in _seen_qr:
        _seen_qr.add((q, prefix))
        _queries_by_repo[prefix].append(q)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int((p / 100.0) * (len(s) - 1)))]


def _lat_summary(lats: list[float]) -> dict:
    if not lats:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0, "over_100ms": 0}
    return {
        "mean": round(sum(lats) / len(lats), 1),
        "p50": round(_pct(lats, 50), 1),
        "p95": round(_pct(lats, 95), 1),
        "max": round(max(lats), 1),
        "over_100ms": sum(1 for x in lats if x > 100),
    }


def _rel(path_str: str, ws: Path) -> str:
    """Normalize a path to be relative to ws (or strip leading ./ for already-relative paths)."""
    p = path_str.replace("\\", "/")
    ws_str = str(ws).replace("\\", "/").rstrip("/") + "/"
    if p.startswith(ws_str):
        return p[len(ws_str) :]
    try:
        return str(Path(path_str).relative_to(ws)).replace("\\", "/")
    except ValueError:
        # Already relative: normalize away leading ./ (.\)
        return str(Path(p)).replace("\\", "/")


_PY_KEYWORDS = frozenset(
    {
        "def",
        "class",
        "import",
        "from",
        "return",
        "if",
        "else",
        "elif",
        "for",
        "while",
        "with",
        "as",
        "try",
        "except",
        "finally",
        "raise",
        "yield",
        "async",
        "await",
        "lambda",
        "pass",
        "break",
        "continue",
    }
)


def _sym(query: str) -> str:
    """Extract the best single symbol token from a raw query string."""
    tokens = [t for t in re.split(r"[\s|,()\[\]]+", query.strip()) if t]
    # Skip leading Python keywords (e.g. "def foo" -> "foo")
    for tok in tokens:
        if tok not in _PY_KEYWORDS:
            return tok
    return tokens[0] if tokens else query


def _extract_paths_text(text: str, ws: Path) -> list[str]:
    """Extract file paths from free-form text, normalized relative to ws."""
    ws_str = str(ws).rstrip("/") + "/"
    seen: set[str] = set()
    result: list[str] = []
    for m in re.finditer(re.escape(ws_str) + r"[^\s'\">,;]+", text):
        rel = m.group()[len(ws_str) :]
        if rel not in seen:
            seen.add(rel)
            result.append(rel)
    # Also catch bare relative paths (tab-sep output like readtags)
    for m in re.finditer(r"(?<![/\w])[\w][\w/.-]+\.[a-zA-Z]{1,5}(?![/\w])", text):
        p = m.group()
        if p not in seen and not p.startswith("/"):
            seen.add(p)
            result.append(p)
    return result


def _rank(ranked_files: list[str], gold_files: list[str]) -> int | None:
    """Return 1-based rank of first gold file, or None."""
    norm_gold = {g.replace("\\", "/") for g in gold_files if g}
    for i, f in enumerate(ranked_files, 1):
        if f.replace("\\", "/") in norm_gold:
            return i
    return None


# Language name map: extension -> (ast-grep lang, generic lang)
_EXT_LANG: list[tuple[str, str]] = [
    ("*.c", "c"),
    ("*.h", "c"),
    ("*.py", "python"),
    ("*.ts", "typescript"),
    ("*.tsx", "tsx"),
    ("*.js", "javascript"),
    ("*.jsx", "jsx"),
    ("*.rs", "rust"),
    ("*.go", "go"),
    ("*.java", "java"),
    ("*.cpp", "cpp"),
    ("*.cc", "cpp"),
    ("*.cxx", "cpp"),
    ("*.rb", "ruby"),
]

# Serena doesn't support 'c' — map generic lang names to Serena-supported ones.
_SERENA_LANG_MAP: dict[str, str] = {
    "c": "cpp",  # closest supported; serena supports cpp / cpp_ccls
    "tsx": "typescript",
    "jsx": "javascript",
}


def _ctags_exclude_args(ws: Path) -> list[str]:
    """Build ctags --exclude flags from .gitignore + standard ignores."""
    args = [
        "--exclude=.git",
        "--exclude=.venv",
        "--exclude=__pycache__",
        "--exclude=node_modules",
    ]
    gitignore = ws / ".gitignore"
    if gitignore.exists():
        args.append(f"--exclude=@{gitignore}")
    return args


def _dominant_lang(ws: Path) -> str:
    """Fast heuristic: first extension with a match at the top two levels."""
    for pat, lang in _EXT_LANG:
        # next() short-circuits — stops at first hit even in huge trees
        if next(ws.glob(pat), None) is not None:
            return lang
        if next(ws.glob(f"*/{pat}"), None) is not None:
            return lang
    return "python"  # safe fallback


# ---------------------------------------------------------------------------
# Provider base
# ---------------------------------------------------------------------------


class Provider:
    """Base class: override start/stop/search_symbol/search_text."""

    name: str = ""

    def start(self, ws: Path) -> None:
        pass

    def stop(self) -> None:
        pass

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        """Return ranked file paths relative to ws for a symbol-definition lookup."""
        return []

    def search_text(self, query: str, ws: Path) -> list[str]:
        """Return ranked file paths relative to ws for a text-content search."""
        return []


# ---------------------------------------------------------------------------
# ctags
# ---------------------------------------------------------------------------


class CtagsProvider(Provider):
    name = "ctags"

    def __init__(self) -> None:
        self._tags_db: Path | None = None
        self._ws: Path | None = None
        self._ctags: Path | None = None
        self._readtags: Path | None = None

    def start(self, ws: Path) -> None:
        from benchmarks.mcp_tools.bench_external_indexers import ensure_universal_ctags

        self._ctags, self._readtags = ensure_universal_ctags()
        self._ws = ws
        fd, tmp = tempfile.mkstemp(suffix=".tags")
        os.close(fd)
        self._tags_db = Path(tmp)
        # Use git ls-files to get only tracked files — respects all nested
        # .gitignore files recursively, avoids indexing .venv / build dirs.
        ls = subprocess.run(
            ["git", "ls-files"],
            cwd=ws,
            capture_output=True,
            timeout=30,
        )
        if ls.returncode == 0 and ls.stdout.strip():
            fd2, flist = tempfile.mkstemp(suffix=".lst")
            os.close(fd2)
            Path(flist).write_bytes(ls.stdout)
            cmd = [
                str(self._ctags),
                "--fields=+nKsS",
                "-f",
                str(self._tags_db),
                "-L",
                flist,
            ]
        else:
            # Not a git repo — fall back to recursive with exclusions
            cmd = [
                str(self._ctags),
                "-R",
                "--fields=+nKsS",
                "-f",
                str(self._tags_db),
                *_ctags_exclude_args(ws),
                ".",
            ]
            flist = None
        try:
            proc = subprocess.run(cmd, cwd=ws, capture_output=True, timeout=600)
        finally:
            if flist:
                Path(flist).unlink(missing_ok=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[:800])

    def stop(self) -> None:
        if self._tags_db and self._tags_db.exists():
            self._tags_db.unlink(missing_ok=True)

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        if not self._readtags or not self._tags_db:
            return []
        sym = _sym(query)
        proc = subprocess.run(
            [str(self._readtags), "-t", str(self._tags_db), "-e", sym],
            capture_output=True,
            text=True,
            timeout=30,
        )
        seen: set[str] = set()
        paths: list[str] = []
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                p = parts[1].replace("\\", "/")
                if p not in seen:
                    seen.add(p)
                    paths.append(p)
        return paths

    def search_text(self, query: str, ws: Path) -> list[str]:
        # ctags has no text/content search
        return []


# ---------------------------------------------------------------------------
# ast-grep
# ---------------------------------------------------------------------------


class AstGrepProvider(Provider):
    name = "ast-grep"

    # Resolved once at class level to avoid per-call subprocess overhead.
    _AST_GREP_BIN: str = ""

    @classmethod
    def _resolve_bin(cls) -> str:
        if cls._AST_GREP_BIN:
            return cls._AST_GREP_BIN
        # Prefer the project-local binary; fall back to npx.
        local = Path(".atelier/bin/ast-grep")
        for candidate in local.rglob("ast-grep"):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                cls._AST_GREP_BIN = str(candidate)
                return cls._AST_GREP_BIN
        # npx fallback (slower but always correct)
        cls._AST_GREP_BIN = "__npx__"
        return cls._AST_GREP_BIN

    def _run(self, pattern: str, ws: Path) -> list[str]:
        lang = _dominant_lang(ws)
        bin_path = self._resolve_bin()
        if bin_path == "__npx__":
            cmd = [
                "npx",
                "--yes",
                "-p",
                "@ast-grep/cli",
                "sg",
                "run",
                "--pattern",
                pattern,
                "--lang",
                lang,
                "--json",
                str(ws),
            ]
        else:
            cmd = [bin_path, "run", "--pattern", pattern, "--lang", lang, "--json", str(ws)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode > 1 or (proc.returncode == 1 and not (proc.stdout or "").strip().startswith("[")):
            return []
        seen: set[str] = set()
        result: list[str] = []
        try:
            items = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            return []
        for item in items:
            p = _rel(str(item.get("file", "")), ws)
            if p and p not in seen:
                seen.add(p)
                result.append(p)
        return result

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        return self._run(_sym(query), ws)

    def search_text(self, query: str, ws: Path) -> list[str]:
        return self._run(query, ws)


# ---------------------------------------------------------------------------
# serena
# ---------------------------------------------------------------------------


class SerenaProvider(Provider):
    name = "serena"

    def __init__(self) -> None:
        self._runner: Any = None
        self._home: Path | None = None

    def start(self, ws: Path) -> None:
        import shutil

        from benchmarks.mcp_tools.bench_external_indexers import SerenaRunner

        # Remove any stale .serena dir left by prior runs so bootstrap doesn't
        # fail with "Project already exists".
        stale = ws / ".serena"
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)

        self._home = Path(tempfile.mkdtemp(prefix="serena-home-"))
        self._runner = SerenaRunner(
            project_root=ws,
            home_dir=self._home,
            project_name="mrr-bench",
            language=_SERENA_LANG_MAP.get(_dominant_lang(ws), _dominant_lang(ws)),
        )
        self._runner.bootstrap()
        self._runner.start()

    def stop(self) -> None:
        if self._runner:
            self._runner.stop()
            self._runner = None
        if self._home and self._home.exists():
            import shutil

            shutil.rmtree(self._home, ignore_errors=True)

    def _query(self, tool_name: str, params: dict) -> str:
        assert self._runner
        try:
            return self._runner.query(tool_name, params)
        except Exception:
            return ""

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        resp = self._query(
            "find_symbol",
            {
                "name_path_pattern": _sym(query),
                "substring_matching": True,
                "max_matches": 20,
                "include_body": False,
                "depth": 0,
            },
        )
        return _extract_paths_text(resp, ws)

    def search_text(self, query: str, ws: Path) -> list[str]:
        resp = self._query(
            "search_for_pattern",
            {"substring_pattern": query, "restrict_search_to_code_files": True},
        )
        return _extract_paths_text(resp, ws)


# ---------------------------------------------------------------------------
# code-index-mcp
# ---------------------------------------------------------------------------


class CodeIndexProvider(Provider):
    name = "code-index-mcp"

    def __init__(self) -> None:
        self._runner: Any = None
        self._ws: Path | None = None

    def start(self, ws: Path) -> None:
        from benchmarks.mcp_tools.bench_external_indexers import (
            CodeIndexRunner,
            default_benchmark_root,
            ensure_code_index_checkout,
        )

        self._ws = ws
        bench_root = default_benchmark_root(ws)
        code_index_repo = ensure_code_index_checkout(bench_root / "code-index-mcp")
        tmp_ws = Path(tempfile.mkdtemp(prefix="cidx-ws-"))
        self._runner = CodeIndexRunner(
            repo_root=ws,
            workspace_root=tmp_ws,
            code_index_repo=code_index_repo,
        )
        self._runner.start()

    def stop(self) -> None:
        self._runner = None

    def _paths_from_result(self, result: dict, ws: Path) -> list[str]:
        seen: set[str] = set()
        paths: list[str] = []
        for item in result.get("results", []) or []:
            for key in ("file", "path", "file_path"):
                raw = item.get(key)
                if raw:
                    p = _rel(str(raw), ws)
                    if p not in seen:
                        seen.add(p)
                        paths.append(p)
                    break
        if not paths:
            paths = _extract_paths_text(json.dumps(result), ws)
        return paths

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        if not self._runner:
            return []
        try:
            result = self._runner.query(_sym(query), file_pattern="*")
        except Exception:
            return []
        return self._paths_from_result(result, ws)

    def search_text(self, query: str, ws: Path) -> list[str]:
        if not self._runner:
            return []
        try:
            result = self._runner.query(query, file_pattern="*")
        except Exception:
            return []
        return self._paths_from_result(result, ws)


# ---------------------------------------------------------------------------
# jcodemunch
# ---------------------------------------------------------------------------


class JCodeMunchProvider(Provider):
    name = "jcodemunch"

    def __init__(self) -> None:
        self._client: Any = None
        self._repo_id: str | None = None
        self._ws: Path | None = None

    def _tool_call(self, name: str, args: dict) -> dict:
        assert self._client
        import json as _json

        response = self._client.call("tools/call", {"name": name, "arguments": args}, timeout=120)
        result = response.get("result", {})
        if result.get("isError"):
            raise RuntimeError(_json.dumps(result))
        return result

    def _content_text_json(self, result: dict) -> dict:
        content = result.get("content", [])
        if content and isinstance(content[0], dict):
            text = content[0].get("text", "{}")
            return json.loads(text)
        return {}

    def start(self, ws: Path) -> None:
        from benchmarks.mcp_tools.bench_external_indexers import run_cmd

        self._ws = ws
        # Index the repo
        idx = run_cmd(
            ["jcodemunch-mcp", "index", str(ws), "--no-ai-summaries"],
            timeout=1800,
        )
        if idx.returncode != 0:
            raise RuntimeError(idx.stderr[:800] or idx.stdout[:800])
        self._client = _JsonRpcLineClient(["jcodemunch-mcp", "serve"])
        self._client.start()
        repo_result = self._tool_call("resolve_repo", {"path": str(ws)})
        payload = self._content_text_json(repo_result)
        self._repo_id = str(payload["repo"])

    def stop(self) -> None:
        if self._client:
            self._client.stop()
            self._client = None

    def _paths_from_result(self, result: dict, ws: Path) -> list[str]:
        text = json.dumps(result)
        return _extract_paths_text(text, ws)

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        if not self._client or not self._repo_id:
            return []
        try:
            result = self._tool_call(
                "search_symbols",
                {
                    "repo": self._repo_id,
                    "query": _sym(query),
                    "language": _dominant_lang(self._ws) if self._ws else "python",
                    "max_results": 20,
                    "detail_level": "compact",
                    "fuzzy": False,
                },
            )
        except Exception:
            return []
        return self._paths_from_result(result, ws)

    def search_text(self, query: str, ws: Path) -> list[str]:
        if not self._client or not self._repo_id:
            return []
        try:
            result = self._tool_call(
                "search_text",
                {"repo": self._repo_id, "query": query, "max_results": 20, "context_lines": 0},
            )
        except Exception:
            return []
        return self._paths_from_result(result, ws)


# ---------------------------------------------------------------------------
# cg (codegraph)
# ---------------------------------------------------------------------------


def _cg_parse_results(stdout: str) -> list[str]:
    try:
        results = json.loads(stdout)
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        if isinstance(results, dict):
            results = list(results.values()) if results else []
        if not isinstance(results, list):
            return []
    except json.JSONDecodeError:
        return []
    files: list[str] = []
    seen: set[str] = set()
    for r in results:
        if isinstance(r, dict):
            node = r.get("node", r)
            path = node.get("filePath", "") or node.get("path", "") or ""
        elif isinstance(r, str):
            path = r
        else:
            continue
        if path and path not in seen:
            seen.add(path)
            files.append(path)
    return files


# ---------------------------------------------------------------------------
# rg — bare ripgrep, no ranking (baseline for text search)
# ---------------------------------------------------------------------------


class RgProvider(Provider):
    name = "rg"

    def start(self, ws: Path) -> None:
        pass  # stateless

    def stop(self) -> None:
        pass

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        return self._rg(query, ws)

    def search_text(self, query: str, ws: Path) -> list[str]:
        return self._rg(query, ws)

    def _rg(self, query: str, ws: Path) -> list[str]:
        try:
            proc = subprocess.run(
                [
                    "rg",
                    "--files-with-matches",
                    "-l",
                    "--no-heading",
                    "--iglob",
                    "!.git",
                    "--iglob",
                    "!.venv",
                    "--iglob",
                    "!node_modules",
                    "--iglob",
                    "!__pycache__",
                    # Use rg's default regex mode — our queries are grep patterns.
                    # Falls back gracefully: rg exits 1 (no match) on bad patterns.
                    query,
                    str(ws),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return []
        if proc.returncode > 1:
            # returncode 1 = no matches (normal); >1 = error
            return []
        seen: set[str] = set()
        result: list[str] = []
        for line in proc.stdout.splitlines():
            p = _rel(line.strip(), ws)
            if p and p not in seen:
                seen.add(p)
                result.append(p)
        return result


class CgProvider(Provider):
    name = "cg"

    def start(self, ws: Path) -> None:
        cg_db = ws / ".codegraph" / "codegraph.db"
        if not cg_db.exists():
            print(f"{_TAG} cg init {ws.name} ...", file=sys.stderr, flush=True)
            t1 = time.perf_counter()
            r = subprocess.run(
                ["codegraph", "init", "-i", str(ws)],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if r.returncode != 0:
                raise RuntimeError(f"codegraph init failed: {r.stderr[:400]}")
            print(f"{_TAG} cg init done in {time.perf_counter() - t1:.1f}s", file=sys.stderr)
        self._ws = ws

    def stop(self) -> None:
        pass

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        r = subprocess.run(
            ["codegraph", "query", "-p", str(ws), "-l", "20", "-j", _sym(query)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            return []
        return _cg_parse_results(r.stdout)

    def search_text(self, query: str, ws: Path) -> list[str]:
        return []  # codegraph has no content/text search


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[Provider]] = {
    "ctags": CtagsProvider,
    "ast-grep": AstGrepProvider,
    "serena": SerenaProvider,
    "code-index-mcp": CodeIndexProvider,
    "jcodemunch": JCodeMunchProvider,
    "cg": CgProvider,
    "rg": RgProvider,
}

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_gold(kind: str, tm: dict, results: dict[tuple[str, str], list[str]]) -> dict:
    """Compute MRR/hit metrics for one gold kind.

    results: {(query, prefix): ranked_file_list}
    """
    agg = {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}
    by_repo: dict[str, dict] = {}
    lats_by_repo: dict[str, list[float]] = defaultdict(list)

    for (q, prefix), files in results.items():
        tids = _q_to_tids.get((q, prefix), {})
        tid = tids.get(kind)
        if not tid:
            continue
        trues = [p.replace("\\", "/") for p in tm.get(tid, []) if p]
        if not trues:
            continue
        r = _rank(files, trues)
        br = by_repo.setdefault(prefix, {"rr": 0.0, "h1": 0, "h3": 0, "n": 0})
        for d in (agg, br):
            d["n"] += 1
            if r:
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
        "by_repo": {
            p: {
                "mrr": round(d["rr"] / max(d["n"], 1), 4),
                "hit1": round(d["h1"] / max(d["n"], 1), 4),
                "hit3": round(d["h3"] / max(d["n"], 1), 4),
                "n": d["n"],
                "latency_ms": _lat_summary(lats_by_repo.get(p, [])),
            }
            for p, d in sorted(by_repo.items())
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if not _golds:
    print(f"{_TAG} no golds loaded", file=sys.stderr)
    sys.exit(1)

provider = _PROVIDERS[PROVIDER]()
total_queries = len(_union)
print(f"{_TAG} repos={len(_queries_by_repo)} queries={total_queries}", file=sys.stderr)

# {(query, prefix): {gold_kind: list[str]}} for scored results
_sym_results: dict[tuple[str, str], list[str]] = {}
_txt_results: dict[tuple[str, str], list[str]] = {}
all_latencies: list[float] = []
lats_by_repo: dict[str, list[float]] = defaultdict(list)

_done = 0
_t0 = time.perf_counter()

for prefix, queries in sorted(_queries_by_repo.items()):
    repo_meta = _all_repos.get(prefix, {})
    ws = Path(repo_meta.get("ws", ""))
    if not ws.exists():
        print(f"{_TAG} skip {prefix}: ws not found ({ws})", file=sys.stderr)
        continue

    print(f"{_TAG} start {prefix} ({len(queries)} queries)", file=sys.stderr, flush=True)
    try:
        provider.start(ws)
    except Exception as exc:
        print(f"{_TAG} {prefix} start failed: {exc}", file=sys.stderr)
        continue

    for q in queries:
        t1 = time.perf_counter()
        try:
            sym_files = provider.search_symbol(q, ws)
        except Exception:
            sym_files = []
        try:
            txt_files = provider.search_text(q, ws)
        except Exception:
            txt_files = []
        elapsed_q = (time.perf_counter() - t1) * 1000.0
        all_latencies.append(elapsed_q)
        lats_by_repo[prefix].append(elapsed_q)
        _sym_results[(q, prefix)] = sym_files
        _txt_results[(q, prefix)] = txt_files
        _done += 1

    try:
        provider.stop()
    except Exception as exc:
        print(f"{_TAG} {prefix} stop error: {exc}", file=sys.stderr)

    # Cumulative progress after every repo — same pattern as fitness_explore_mrr
    _el = time.perf_counter() - _t0
    _rate = _done / _el if _el else 0
    _eta = (total_queries - _done) / _rate if _rate else 0
    print(
        f"{_TAG} {_done}/{total_queries} elapsed={_el:.0f}s rate={_rate:.1f}/s eta={_eta:.0f}s",
        file=sys.stderr,
        flush=True,
    )


# Score each gold kind.
# definition -> sym_results; content -> txt_results
# swebench -> merge both (queries are a mix of symbol-lookup and text-search;
#             take sym hits first as they are more precise, then text hits).
def _merged(key: tuple[str, str]) -> list[str]:
    sym = _sym_results.get(key, [])
    txt = _txt_results.get(key, [])
    seen: set[str] = set(sym)
    return sym + [f for f in txt if f not in seen]


_gold_scores: dict[str, dict] = {}
for _kind, _, _tm in _golds:
    if _kind == "definition":
        scored = _sym_results
    elif _kind == "content":
        scored = _txt_results
    else:  # swebench or any future mixed kind
        scored = {k: _merged(k) for k in set(_sym_results) | set(_txt_results)}
    _gold_scores[_kind] = _score_gold(_kind, _tm, scored)

# Attach per-repo latencies to by_repo entries
for _gk, gdata in _gold_scores.items():
    for prefix, rd in gdata.get("by_repo", {}).items():
        rd["latency_ms"] = _lat_summary(lats_by_repo.get(prefix, []))

# Primary metrics (first gold kind)
_primary = _gold_scores[_golds[0][0]]
out = {
    **_primary,
    "latency_ms": _lat_summary(all_latencies),
    "golds": _gold_scores,
    "provider": PROVIDER,
    "mode": f"ext[{PROVIDER}]",
}

print(json.dumps(out, ensure_ascii=False))

# Summary — match fitness_explore_mrr.py format with per-repo breakdown
print("\n" + "─" * 60, file=sys.stderr)
print(f"  provider={PROVIDER}", file=sys.stderr)
for gk, gd in _gold_scores.items():
    print(f"  gold={gk:<18} MRR {gd['mrr']:.4f}  hit@1 {gd['hit1']:.4f}  n={gd['n']}", file=sys.stderr)
lat = out["latency_ms"]
print(f"  lat  mean={lat['mean']:.0f}ms  p95={lat['p95']:.0f}ms  max={lat['max']:.0f}ms", file=sys.stderr)
# Per-repo rows sorted by primary-gold MRR ascending (worst first)
_primary_gk = _golds[0][0]
_by_repo_sorted = sorted(
    _gold_scores[_primary_gk].get("by_repo", {}).items(),
    key=lambda kv: kv[1].get("mrr", 0),
)
for _rprefix, _rd in _by_repo_sorted:
    _rmrr = _rd.get("mrr", 0)
    _rn = _rd.get("n", 0)
    _rlat = _rd.get("latency_ms") or {}
    _rp95 = _rlat.get("p95", 0)
    _rp100 = _rlat.get("max", 0)
    _icon = "✓" if _rmrr >= 0.9 else ("~" if _rmrr >= 0.5 else "✗")
    _short = _rprefix.split("__")[-1] if "__" in _rprefix else _rprefix
    # Build def/con MRR string
    _mrr_parts = []
    for _gk in ("definition", "content"):
        _gk_repo = (_gold_scores.get(_gk) or {}).get("by_repo", {}).get(_rprefix)
        if _gk_repo and isinstance(_gk_repo, dict):
            _mrr_parts.append(f"{_gk_repo['mrr']:.3f}")
    _mrr_str = "/".join(_mrr_parts) if len(_mrr_parts) > 1 else f"{_rmrr:.3f}"
    print(
        f"  {_icon}  {_short:<22} n={_rn:<4} MRR={_mrr_str}  p95={_rp95:.0f}ms  p100={_rp100:.0f}ms",
        file=sys.stderr,
    )
print("─" * 60 + "\n", file=sys.stderr)
