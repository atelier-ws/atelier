"""Retrieval provider MRR benchmark -- every provider, Atelier included, over
the same stdio/CLI surface. No provider gets in-process shortcuts.

Providers: atelier / ctags / ast-grep / serena / code-index-mcp / jcodemunch /
cg / rg / cmm. Same gold set and output JSON format as the retired
fitness_explore_mrr.py; history + delta reporting live here now.

Run via:
    uv run python benchmarks/codebench/eval_external_provider_mrr.py --provider atelier
    uv run python benchmarks/codebench/eval_external_provider_mrr.py --provider ctags
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
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
        self.call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "atelier-bench", "version": "1"},
                "capabilities": {},
            },
        )
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
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, ensure_ascii=False) + "\n"
        )
        self.proc.stdin.flush()

    def call(self, method: str, params: dict[str, Any], *, timeout: float = 60) -> dict[str, Any]:
        assert self.proc is not None and self.proc.stdin is not None
        request_id = self._next_id
        self._next_id += 1
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}, ensure_ascii=False)
            + "\n"
        )
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
    choices=["atelier", "ctags", "ast-grep", "serena", "code-index-mcp", "jcodemunch", "cg", "rg", "cmm"],
)
_parser.add_argument("--full", action="store_true")
_parser.add_argument("--sample", type=int, default=None)
_parser.add_argument("--repo", default=os.environ.get("FITNESS_REPO", ""))
_args, _ = _parser.parse_known_args()

PROVIDER = _args.provider
# Channel label: the CLI runs Atelier channel variants (lexical / lexical+zoekt /
# lexical+zoekt+semantic) as env toggles on the same provider; the label keeps
# their history and tags distinguishable.
_LABEL = os.environ.get("EVAL_CHANNEL_LABEL", PROVIDER)
_TAG = f"[ext:{_LABEL}]"  # per-channel tag so parallel runs don't interleave identically
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


class _SerenaMCPClient:
    """Non-destructive MCP stdio client for Serena.

    Unlike ``_JsonRpcLineClient`` this client **never kills** the subprocess on
    timeout — it simply raises ``TimeoutError`` so the caller can decide whether
    to retry or skip.  This is essential because Serena's first ``find_symbol``
    call on a cold project can take 60-120s to start the LSP server.
    """

    def __init__(self, command: list[str], *, env: dict[str, str] | None = None) -> None:
        self.command = command
        self.env = env
        self.proc: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._lock = threading.Lock()

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=self.env,
        )
        # MCP handshake
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "atelier-bench", "version": "1"},
                    "capabilities": {},
                },
            }
        )
        self._recv(timeout=30)  # initialize response
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def _send(self, msg: dict) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _recv(self, *, timeout: float) -> dict:
        """Read one JSON-RPC line from stdout with a wall-clock timeout.

        Does **not** kill the subprocess if the timeout fires — only raises.
        """
        assert self.proc is not None and self.proc.stdout is not None
        # Use select/poll on Unix to avoid killing the process
        import select

        ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not ready:
            raise TimeoutError(f"no response from serena MCP server after {timeout:.0f}s")
        line = self.proc.stdout.readline()
        if not line:
            raise BrokenPipeError("serena MCP server closed stdout")
        msg = json.loads(line)
        assert isinstance(msg, dict)
        return msg

    def call(self, method: str, params: dict, *, timeout: float = 300) -> dict:
        """Send a JSON-RPC request and wait for the matching response."""
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"serena MCP call '{method}' timed out after {timeout:.0f}s")
                try:
                    msg = self._recv(timeout=remaining)
                except TimeoutError:
                    raise
                if isinstance(msg, dict) and msg.get("id") == req_id:
                    return msg
                # Skip other messages (notifications, responses to other requests)

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=6)
        except Exception:
            self.proc.kill()
        self.proc = None


class SerenaProvider(Provider):
    """Persistent MCP-server-based provider for Serena.

    Class-level state shares a single ``serena start-mcp-server --transport stdio``
    process across all repos in a benchmark run, avoiding the per-repo
    ``serena init`` + ``project create`` + server start/stop overhead.

    Projects that already have a ``.serena/`` directory are reused as-is; only
    missing projects are created on the fly.
    """

    name = "serena"

    # -- Class-level persistent state (shared across all repos) ---------------
    _mcp: _SerenaMCPClient | None = None
    _serena_home: Path | None = None
    _setup_done: bool = False

    # -- Per-instance state ---------------------------------------------------
    def __init__(self) -> None:
        self._lang: str = "python"

    # -- Global setup (once per script invocation) ----------------------------

    @classmethod
    def _global_init(cls) -> None:
        if cls._setup_done:
            return
        cls._serena_home = Path(tempfile.mkdtemp(prefix="serena-bench-"))
        env = {**os.environ, "HOME": str(cls._serena_home)}
        proc = subprocess.run(
            ["serena", "init", "-b", "LSP"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"serena global init failed: {(proc.stderr or proc.stdout)[:800]}")
        cls._setup_done = True

    @classmethod
    def _ensure_mcp(cls) -> _SerenaMCPClient:
        if cls._mcp is not None:
            return cls._mcp
        cls._global_init()
        env = {**os.environ, "HOME": str(cls._serena_home)}
        mcp = _SerenaMCPClient(
            ["serena", "start-mcp-server", "--transport", "stdio"],
            env=env,
        )
        mcp.start()
        cls._mcp = mcp
        import atexit

        atexit.register(cls._global_cleanup)
        return mcp

    @classmethod
    def _global_cleanup(cls) -> None:
        if cls._mcp is not None:
            with contextlib.suppress(Exception):
                cls._mcp.stop()
            cls._mcp = None
        if cls._serena_home is not None and cls._serena_home.exists():
            import shutil

            shutil.rmtree(cls._serena_home, ignore_errors=True)
            cls._serena_home = None

    # -- Per-repo lifecycle ---------------------------------------------------

    def start(self, ws: Path) -> None:
        """Activate the serena project for *ws* via the shared MCP server.

        Creates the project first if no ``.serena/`` directory exists yet.
        """
        self._lang = _SERENA_LANG_MAP.get(_dominant_lang(ws), _dominant_lang(ws))
        mcp = self._ensure_mcp()

        # Lazily create the project when the workspace has no .serena/ dir.
        if not (ws / ".serena" / "project.yml").exists():
            env = {**os.environ, "HOME": str(self._serena_home)}
            subprocess.run(
                [
                    "serena",
                    "project",
                    "create",
                    str(ws),
                    "--name",
                    f"bench-{ws.name}",
                    "--language",
                    self._lang,
                ],
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )

        # Activate the project through the MCP server so subsequent tool
        # calls (find_symbol / search_for_pattern) target this repo.
        result = mcp.call(
            "tools/call",
            {"name": "activate_project", "arguments": {"project": str(ws)}},
            timeout=180,
        )
        if result.get("result", {}).get("isError"):
            err_text = result.get("result", {}).get("content", [{}])[0].get("text", repr(result))
            raise RuntimeError(f"serena activate_project failed: {err_text}")

    def stop(self) -> None:
        """No per-repo teardown — the shared MCP server stays alive."""
        pass

    # -- Tool calls via MCP ---------------------------------------------------

    def _call_tool(self, name: str, args: dict[str, object]) -> str:
        mcp = self._ensure_mcp()
        try:
            result = mcp.call("tools/call", {"name": name, "arguments": args}, timeout=300)
        except Exception:
            return ""
        content = result.get("result", {}).get("content", [])
        if result.get("result", {}).get("isError"):
            return ""
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        return "\n".join(texts)

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        resp = self._call_tool(
            "find_symbol",
            {
                "name_path_pattern": _sym(query),
                "substring_matching": True,
                "max_matches": 20,
                "include_body": False,
            },
        )
        return _extract_paths_text(resp, ws)

    def search_text(self, query: str, ws: Path) -> list[str]:
        resp = self._call_tool(
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
            bench_tools_root,
            ensure_code_index_checkout,
            ensure_code_index_runtime,
        )

        self._ws = ws
        # Single shared checkout under ~/.atelier/_bench_tools/ so we don't clone
        # a fresh copy for every gold repo workspace, and so python_bin is always
        # an absolute Path (no cwd-relative confusion in run_cmd).
        code_index_repo = ensure_code_index_checkout(bench_tools_root() / "code-index-mcp")
        # Pre-warm the venv before creating the runner so any uv sync failure
        # surfaces during start() rather than inside the subprocess -- and so
        # python_bin is always an absolute Path (no cwd-relative confusion).
        python_bin = ensure_code_index_runtime(code_index_repo)
        tmp_ws = Path(tempfile.mkdtemp(prefix="cidx-ws-"))
        self._runner = CodeIndexRunner(
            repo_root=ws,
            workspace_root=tmp_ws,
            code_index_repo=code_index_repo,
        )
        self._runner.start(python_bin=python_bin)

    def stop(self) -> None:
        if self._runner is not None:
            with contextlib.suppress(Exception):
                self._runner.stop()
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
    """Persistent ``codegraph serve --mcp`` shared across all repos.

    The one-shot ``codegraph query`` CLI pays ~110ms of node startup + db
    open per call vs ~2ms for the same search over MCP, and
    ``codegraph_search`` takes ``projectPath`` per call, so a single server
    covers every gold repo (same pattern as SerenaProvider).
    """

    name = "cg"

    _mcp: _JsonRpcLineClient | None = None

    # One `path:line` line per search result in the markdown response.
    _RESULT_LINE = re.compile(r"^(\S+\.[A-Za-z0-9]{1,5}):\d+$", re.MULTILINE)

    @classmethod
    def _ensure_mcp(cls) -> _JsonRpcLineClient:
        if cls._mcp is not None:
            return cls._mcp
        client = _JsonRpcLineClient(["codegraph", "serve", "--mcp"])
        client.start()
        cls._mcp = client
        import atexit

        atexit.register(cls._teardown)
        return client

    @classmethod
    def _teardown(cls) -> None:
        if cls._mcp is not None:
            with contextlib.suppress(Exception):
                cls._mcp.stop()
            cls._mcp = None

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
        # Warm-up query: the server lazily opens/syncs a project on first
        # touch (seconds on a cold repo) — pay that here, not in query stats.
        self.search_symbol(ws.name, ws)

    def stop(self) -> None:
        pass  # shared MCP server stays alive; torn down atexit

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        cls = type(self)
        try:
            response = cls._ensure_mcp().call(
                "tools/call",
                {
                    "name": "codegraph_search",
                    "arguments": {"query": _sym(query), "limit": 20, "projectPath": str(ws)},
                },
                timeout=120,
            )
        except Exception:
            cls._teardown()  # dead/hung server: restart lazily on the next call
            return []
        result = response.get("result", {})
        if result.get("isError"):
            return []
        text = "\n".join(
            c.get("text", "") for c in result.get("content", []) if isinstance(c, dict) and c.get("type") == "text"
        )
        seen: set[str] = set()
        files: list[str] = []
        for m in self._RESULT_LINE.finditer(text):
            p = _rel(m.group(1), ws)
            if p not in seen:
                seen.add(p)
                files.append(p)
        return files

    def search_text(self, query: str, ws: Path) -> list[str]:
        return []  # codegraph has no content/text search


# ---------------------------------------------------------------------------
# cmm (codebase-memory-mcp)
# ---------------------------------------------------------------------------

_CMM_VERSION = "v0.8.1"
_CMM_ASSET = "codebase-memory-mcp-linux-amd64.tar.gz"
_CMM_HOME = Path(os.environ.get("CMM_HOME", "/tmp/cmm-bench")).resolve()


class CmmProvider(Provider):
    """DeusData's codebase-memory-mcp: a single static Go binary driven in
    one-shot `cli <tool> '<json>'` mode -- no persistent MCP server, so
    start()/stop() manage the binary + per-repo index rather than a long-lived
    process (the same on-disk graph.db is read fresh on every call)."""

    name = "cmm"

    def __init__(self) -> None:
        self._bin: Path | None = None
        self._env: dict[str, str] = {}
        self._project: str | None = None

    @staticmethod
    def _ensure_binary() -> Path:
        env_bin = os.environ.get("CMM_BIN")
        if env_bin and Path(env_bin).is_file():
            return Path(env_bin)
        bindir = _CMM_HOME / "bin"
        binpath = bindir / "codebase-memory-mcp"
        if binpath.is_file():
            return binpath
        bindir.mkdir(parents=True, exist_ok=True)
        tgz = bindir / _CMM_ASSET
        url = f"https://github.com/DeusData/codebase-memory-mcp/releases/download/{_CMM_VERSION}/{_CMM_ASSET}"
        print(f"{_TAG} downloading {url}", file=sys.stderr, flush=True)
        urllib.request.urlretrieve(url, tgz)  # nosec - pinned release asset
        with tarfile.open(tgz) as tf:
            tf.extract("codebase-memory-mcp", path=bindir)
        binpath.chmod(0o755)
        return binpath

    def _cli(self, tool: str, args: dict, timeout: int = 120) -> dict:
        assert self._bin is not None
        proc = subprocess.run(
            [str(self._bin), "cli", tool, json.dumps(args)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=self._env,
        )
        out = proc.stdout.strip()
        if not out:
            return {}
        try:
            return cast(dict, json.loads(out))
        except json.JSONDecodeError:
            for line in reversed(out.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        return cast(dict, json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return {}

    def _paths(self, result: dict, key: str, ws: Path, limit: int = 10) -> list[str]:
        files: list[str] = []
        seen: set[str] = set()
        for it in result.get("results", []) or []:
            raw = str(it.get(key) or it.get("file_path") or it.get("file") or "")
            f = _rel(raw, ws) if raw else ""
            if f and f not in seen:
                seen.add(f)
                files.append(f)
            if len(files) >= limit:
                break
        return files

    def start(self, ws: Path) -> None:
        self._bin = self._ensure_binary()
        self._env = dict(os.environ)
        home = _CMM_HOME / "home"
        home.mkdir(parents=True, exist_ok=True)
        self._env["HOME"] = str(home)
        idx = self._cli("index_repository", {"repo_path": str(ws), "mode": "full"}, timeout=3600)
        project = idx.get("project")
        if not project or (idx.get("status") != "indexed" and not idx.get("nodes")):
            raise RuntimeError(f"cmm index failed: {json.dumps(idx)[:400]}")
        self._project = project

    def stop(self) -> None:
        self._project = None  # one-shot CLI -- no persistent process to tear down

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        if not self._project:
            return []
        res = self._cli("search_graph", {"project": self._project, "query": query, "limit": 10})
        return self._paths(res, "file_path", ws)

    def search_text(self, query: str, ws: Path) -> list[str]:
        if not self._project:
            return []
        res = self._cli(
            "search_code",
            {"project": self._project, "pattern": query, "limit": 10, "mode": "compact"},
        )
        return self._paths(res, "file", ws)


# ---------------------------------------------------------------------------
# atelier — the shipped Atelier MCP server, treated as just another provider
# ---------------------------------------------------------------------------


class AtelierProvider(Provider):
    """Atelier's stock MCP server over stdio, no special treatment.

    Launches ``atelier mcp`` per workspace and calls the shipped ``code_search``
    tool with the RAW query (the surface agents actually use -- no ``_sym()``
    shaping, or MRR loses continuity with the retired fitness_explore_mrr
    history). Measures engine + serialization + transport end-to-end.

    DB routing without touching the server: the provisioned index (and its
    sibling intel/fts/vectors DBs) is symlinked into a bench ATELIER_ROOT at
    the engine's default ``workspaces/<key>/`` location, so the server
    resolves it exactly as production would. The server's own startup warm
    path (page cache, centrality, ANN matrix, zoekt webserver) covers cold
    costs; one untimed warm-up query in start() absorbs any residual
    first-query wait (zoekt readiness) so timed queries measure steady state.

    ``search_symbol``/``search_text`` share one memoized explore per query:
    explore is Atelier's single retrieval surface for both, exactly as the
    fitness benchmark measured it (latency is gold-independent).
    """

    name = "atelier"

    _STORE_ROOT = Path(os.environ.get("ATELIER_BENCH_STORE", "/tmp/atelier-bench-store"))

    def __init__(self) -> None:
        self._client: _JsonRpcLineClient | None = None
        self._memo: dict[str, list[str]] = {}

    def _route_db(self, ws: Path) -> None:
        """Symlink the provisioned per-repo DBs into the engine-default layout."""
        from atelier.core.foundation.paths import workspace_key  # src/ is on sys.path

        meta = next((m for m in _all_repos.values() if Path(m.get("ws", "")) == ws), {})
        db = Path(meta["db"]) if meta.get("db") else None
        if db is None or not db.exists():
            return  # no prebuilt index: the server will build one on demand
        ws_dir = self._STORE_ROOT / "workspaces" / workspace_key(ws.resolve())
        ws_dir.mkdir(parents=True, exist_ok=True)
        links = {"code_context.sqlite": db}
        for sibling in ("intel.sqlite", "fts.sqlite", "vectors.sqlite"):
            src = db.parent / sibling
            if src.exists():
                links[sibling] = src
        for link_name, target in links.items():
            link = ws_dir / link_name
            if not link.exists():
                link.symlink_to(target)

    def start(self, ws: Path) -> None:
        self._memo = {}
        self._route_db(ws)
        env = {
            **os.environ,
            "ATELIER_ROOT": str(self._STORE_ROOT),
            "ATELIER_WORKSPACE_ROOT": str(ws),
            # the candidate/working-tree code, not an installed wheel
            "PYTHONPATH": "src" + os.pathsep + os.environ.get("PYTHONPATH", ""),
            # let the untimed warm-up absorb the one-time zoekt shard load
            "ATELIER_ZOEKT_READY_TIMEOUT_S": os.environ.get("ATELIER_ZOEKT_READY_TIMEOUT_S", "30"),
        }
        # Host workspace vars outrank ATELIER_WORKSPACE_ROOT in the server's
        # resolution; a bench run inside Claude Code/Cursor would otherwise
        # inherit them and silently search the WRONG repo.
        for host_var in ("CLAUDE_WORKSPACE_ROOT", "CURSOR_WORKSPACE_ROOT", "VSCODE_CWD", "CLAUDE_PROJECT_DIR"):
            env.pop(host_var, None)
        client = _JsonRpcLineClient(
            [sys.executable, "-c", "from atelier.gateway.adapters.mcp_server import main; main()"],
            cwd=Path.cwd(),
            env=env,
        )
        client.start()
        self._client = client
        # Untimed warm-up (same pattern as CgProvider): pays engine init +
        # readiness waits here, not in the timed query stats.
        with contextlib.suppress(Exception):
            self._search(f"warmup {ws.name}", ws, timeout=240)
        self._memo = {}

    def stop(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.stop()
        self._client = None
        self._memo = {}

    def _paths_from_payload(self, payload: dict, ws: Path) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []

        def _add(raw: object) -> None:
            if raw:
                p = _rel(str(raw), ws)
                if p and p not in seen:
                    seen.add(p)
                    out.append(p)

        # `files` are the ranked top matches; `candidate_files` extend the
        # ranked tail. Same order tool_explore returned them.
        for f in payload.get("files", []) or []:
            if isinstance(f, dict):
                _add(f.get("path") or f.get("file_path"))
        for c in payload.get("candidate_files", []) or []:
            _add(c)
        return out

    def _search(self, query: str, ws: Path, *, timeout: float = 120) -> list[str]:
        if query in self._memo:
            return self._memo[query]
        if self._client is None:
            return []
        response = self._client.call(
            "tools/call",
            {"name": "code_search", "arguments": {"query": query, "max_files": 10}},
            timeout=timeout,
        )
        result = response.get("result", {})
        if result.get("isError"):
            self._memo[query] = []
            return []
        payload: dict = result.get("structuredContent") or {}
        if not payload:
            for chunk in result.get("content", []) or []:
                if isinstance(chunk, dict) and chunk.get("type") == "text":
                    with contextlib.suppress(json.JSONDecodeError):
                        payload = json.loads(chunk.get("text", ""))
                        break
        files = self._paths_from_payload(payload, ws) if payload else []
        if not files:  # last resort: scrape paths from raw text
            files = _extract_paths_text(json.dumps(result), ws)
        self._memo[query] = files
        return files

    def search_symbol(self, query: str, ws: Path) -> list[str]:
        try:
            return self._search(query, ws)
        except Exception:
            return []

    def search_text(self, query: str, ws: Path) -> list[str]:
        try:
            return self._search(query, ws)
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[Provider]] = {
    "atelier": AtelierProvider,
    "ctags": CtagsProvider,
    "ast-grep": AstGrepProvider,
    "serena": SerenaProvider,
    "code-index-mcp": CodeIndexProvider,
    "jcodemunch": JCodeMunchProvider,
    "cg": CgProvider,
    "rg": RgProvider,
    "cmm": CmmProvider,
}

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_gold(kind: str, tm: dict, results: dict[tuple[str, str], list[str]]) -> dict:
    """Compute MRR/hit metrics for one gold kind.

    results: {(query, prefix): ranked_file_list}
    """
    agg = {"rr": 0.0, "h1": 0, "h2": 0, "h3": 0, "n": 0}
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
        br = by_repo.setdefault(prefix, {"rr": 0.0, "h1": 0, "h2": 0, "h3": 0, "n": 0})
        for d in (agg, br):
            d["n"] += 1
            if r:
                d["rr"] += 1.0 / r
                if r == 1:
                    d["h1"] += 1
                if r <= 2:
                    d["h2"] += 1
                if r <= 3:
                    d["h3"] += 1

    return {
        "mrr": round(agg["rr"] / max(agg["n"], 1), 4),
        "hit1": round(agg["h1"] / max(agg["n"], 1), 4),
        "hit2": round(agg["h2"] / max(agg["n"], 1), 4),
        "hit3": round(agg["h3"] / max(agg["n"], 1), 4),
        "n": agg["n"],
        "by_repo": {
            p: {
                "mrr": round(d["rr"] / max(d["n"], 1), 4),
                "hit1": round(d["h1"] / max(d["n"], 1), 4),
                "hit2": round(d["h2"] / max(d["n"], 1), 4),
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
_base_mode = "full" if FULL else (f"sample={SAMPLE}" if SAMPLE else "default")
_mode = f"{_base_mode}[{_LABEL}]"
if REPO_FILTER:
    _mode += f" repo={REPO_FILTER}"
out = {
    **_primary,
    "latency_ms": _lat_summary(all_latencies),
    "golds": _gold_scores,
    "provider": PROVIDER,
    "mode": _mode,
}

print(json.dumps(out, ensure_ascii=False))

# ── History: persist this run so trends and deltas survive across runs ────────
_HISTORY = Path("benchmarks/codebench/results/mrr_history.jsonl")
_HISTORY.parent.mkdir(parents=True, exist_ok=True)
try:
    _sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    _dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    _sha_label = _sha + ("+" if _dirty else "")
except Exception:
    _sha_label = "unknown"

from datetime import UTC  # noqa: E402
from datetime import datetime as _datetime  # noqa: E402

_record = {
    "ts": _datetime.now(UTC).isoformat(timespec="seconds"),
    "sha": _sha_label,
    "mode": _mode,
    "mrr": out["mrr"],
    "hit1": out["hit1"],
    "hit3": out["hit3"],
    "n": out["n"],
    "latency_ms": out["latency_ms"],
    "by_repo": out.get("by_repo", {}),
    "golds": out["golds"],
}
with _HISTORY.open("a") as _fh:
    _fh.write(json.dumps(_record) + "\n")

try:
    _runs = [json.loads(line) for line in _HISTORY.read_text().splitlines() if line.strip()]
except Exception:
    _runs = [_record]
# Only compare against a previous run of the same mode — cross-mode comparisons
# (different sample sizes / channels) skew the MRR baseline.
_prev = next((r for r in reversed(_runs[:-1]) if r.get("mode") == _mode), None)

# Summary — match fitness_explore_mrr.py format with per-repo breakdown
print("\n" + "─" * 60, file=sys.stderr)
print(f"  {_record['ts'][:16]}  {_sha_label}  [{_mode}]  provider={PROVIDER}", file=sys.stderr)
for gk, gd in _gold_scores.items():
    print(
        f"  gold={gk:<18} MRR {gd['mrr']:.4f}  hit@1 {gd['hit1']:.4f}  hit@3 {gd['hit3']:.4f}  n={gd['n']}",
        file=sys.stderr,
    )
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

# ── Delta vs previous same-mode run ──────────────────────────────────────────
if _prev:
    print("", file=sys.stderr)
    _pmrr = _prev["mrr"]
    _dmrr = out["mrr"] - _pmrr
    _sign = "+" if _dmrr >= 0 else ""
    print(
        f"  vs {_prev['ts'][:16]} [{_prev['mode']}]  MRR {_pmrr:.4f} → {out['mrr']:.4f}  ({_sign}{_dmrr:.4f})",
        file=sys.stderr,
    )
    # per-repo deltas — only show movers
    _by_now = out.get("by_repo", {}) or {}
    _by_prev = _prev.get("by_repo", {}) or {}
    _movers = []
    for _rname in set(_by_now) | set(_by_prev):
        _cm = (_by_now.get(_rname) or {}).get("mrr", 0)
        _pm = (_by_prev.get(_rname) or {}).get("mrr", 0)
        if _cm != _pm:
            _movers.append((_rname.split("__")[-1], _pm, _cm, _cm - _pm))
    _movers.sort(key=lambda x: x[3])
    for _rn2, _pm, _cm, _dd in _movers:
        _sign2 = "+" if _dd >= 0 else ""
        print(f"    {_rn2:<22}  {_pm:.3f} → {_cm:.3f}  ({_sign2}{_dd:.3f})", file=sys.stderr)
print("─" * 60 + "\n", file=sys.stderr)
