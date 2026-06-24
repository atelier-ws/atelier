"""Managed Zoekt runtime for large-repo text search routing."""

from __future__ import annotations

import atexit
import base64
import json
import os
import shutil
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from atelier.core.foundation.paths import default_store_root

from .binary import ZoektBinaryResolution, discover_zoekt_binary

_BRIDGE_SENTINEL = "__ATELIER_ZOEKT_END__"
_DOCKER_NOFILE = "1048576:1048576"
_STARTUP_TIMEOUT_SECONDS = 60.0
_POLL_INTERVAL_SECONDS = 0.25
_SKIP_ROOTS = {".git", ".jj", ".atelier", ".venv", "node_modules", "dist", "build", "__pycache__"}


@dataclass(frozen=True)
class ZoektHealth:
    ok: bool
    backend: str
    binary_path: str | None
    index_age_seconds: int | None


class ZoektServer:
    """Shared Zoekt runtime with session-scoped lifecycle reuse."""

    def __init__(self, repo_root: Path, *, resolution: ZoektBinaryResolution | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.resolution = resolution
        self._lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._bridge: subprocess.Popen[str] | None = None
        self._container_id: str | None = None
        self._host_search_binary: Path | None = None
        from atelier.core.foundation.paths import workspace_key

        self._container_name = f"atelier-zoekt-{workspace_key(self.repo_root)[:40]}-{os.getpid()}"
        self._started_at: float | None = None
        self.start_count = 0

    @property
    def runtime_root(self) -> Path:
        from atelier.core.foundation.paths import workspace_key

        workspace_hash = workspace_key(self.repo_root)
        return default_store_root() / "workspaces" / workspace_hash / "zoekt"

    @property
    def index_root(self) -> Path:
        return self.runtime_root / "index"

    @property
    def state_path(self) -> Path:
        return self.runtime_root / "state.json"

    @property
    def input_root(self) -> Path:
        return self.runtime_root / "input"

    def ensure_started(self) -> str:
        """Register this workspace against an existing Zoekt index.

        Only wires up the binary handle and returns.  Never builds or
        rebuilds the index -- that is ``build_index()``'s job, called
        offline from ``atelier code index`` / ``atelier zoekt up``.
        Raises ``RuntimeError`` if no index is available so the caller
        can degrade gracefully instead of paying an inline build cost.
        """
        with self._lock:
            if self._is_ready():
                return self.handle
            resolution = self.resolution or discover_zoekt_binary(self.repo_root)
            if not resolution.available:
                raise RuntimeError(resolution.reason or "zoekt runtime unavailable")
            self.resolution = resolution
            if resolution.runtime == "docker":
                # Docker runtime must be started (container launch is fast).
                self._start_docker_runtime(resolution)
            else:
                # Host binary mode: register against the on-disk index.
                # _is_ready() already verified state.json + shards exist and
                # restored _host_search_binary, so we only reach here when the
                # disk index is genuinely absent -- surface that as an error.
                raise RuntimeError(
                    f"no Zoekt index found at {self.index_root} -- "
                    "run 'atelier code index' or 'atelier zoekt up' to build it first"
                )
            self.start_count += 1
            return self.handle

    def ensure_started_and_build(self) -> str:
        """Start Zoekt, building the index if missing.  For indexing routes only."""
        with self._lock:
            if self._is_ready():
                return self.handle
            resolution = self.resolution or discover_zoekt_binary(self.repo_root)
            if not resolution.available:
                raise RuntimeError(resolution.reason or "zoekt runtime unavailable")
            self.resolution = resolution
            if resolution.runtime == "docker":
                self._start_docker_runtime(resolution)
            else:
                self.build_index(resolution)
                self._started_at = self._load_started_at()
            self.start_count += 1
            return self.handle

    @property
    def handle(self) -> str:
        if self.resolution is None:
            raise RuntimeError("Zoekt runtime has not been started")
        if self.resolution.runtime == "docker":
            if not self._container_id:
                raise RuntimeError("Zoekt container has not been started")
            return f"docker://{self._container_id}"
        return f"binary://{self.index_root}"

    def health(self) -> ZoektHealth:
        self.ensure_started()
        runtime_ref = None
        if self.resolution is not None:
            runtime_ref = self.resolution.image_ref or (
                str(self.resolution.path) if self.resolution.path is not None else None
            )
        index_age_seconds = None
        if self._started_at is not None:
            index_age_seconds = int(max(0, time.time() - self._started_at))
        return ZoektHealth(
            ok=True,
            backend="zoekt",
            binary_path=runtime_ref,
            index_age_seconds=index_age_seconds,
        )

    def raw_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_started()
        if self.resolution is None:
            raise RuntimeError("Zoekt runtime has not been resolved")
        if self.resolution.runtime == "docker":
            return self._bridge_request(payload)
        return self._run_host_search(payload)

    def stop(self) -> None:
        with self._lock:
            if self._bridge is not None:
                bridge = self._bridge
                self._bridge = None
                with suppress(Exception):
                    if bridge.stdin is not None:
                        bridge.stdin.close()
                with suppress(Exception):
                    bridge.terminate()
                try:
                    bridge.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # SIGTERM did not land; escalate to SIGKILL and reap so the
                    # docker exec child is not left defunct.
                    with suppress(Exception):
                        bridge.kill()
                    with suppress(Exception):
                        bridge.wait(timeout=5)
            if self._container_id is not None:
                container_id = self._container_id
                self._container_id = None
                _run_command(["docker", "stop", container_id], check=False, timeout=30)
            self._host_search_binary = None
            self._started_at = None

    def _is_ready(self) -> bool:
        if self.resolution is None:
            return False
        if self.resolution.runtime == "docker":
            return self._container_id is not None and self._bridge is not None and self._bridge.poll() is None
        # Host binary mode: check on-disk state so a prior-process prewarm
        # (entry-script or `atelier code index`) survives MCP server restart
        # without a full rebuild.  The in-process _host_search_binary pointer
        # is lazily restored from the resolution if disk state is present.
        if not self.state_path.exists() or not any(self.index_root.glob("*.zoekt")):
            return False
        if self._host_search_binary is None and self.resolution is not None:
            with suppress(Exception):
                self._host_search_binary, *_ = _resolve_host_binaries(self.resolution)
        return self._host_search_binary is not None

    def _start_docker_runtime(self, resolution: ZoektBinaryResolution) -> None:
        if not resolution.image_ref:
            raise RuntimeError("managed docker runtime is missing an image reference")
        self._prepare_runtime_dirs()
        self._refresh_input_links()
        inspect = _run_command(["docker", "image", "inspect", resolution.image_ref], check=False, timeout=30)
        if inspect.returncode != 0:
            _run_command(["docker", "pull", resolution.image_ref], timeout=300)
        # A previous bridge timeout kills the bridge Popen but leaves the
        # named container running; remove any leftover so this start is
        # idempotent and `docker run --name` does not collide.
        _run_command(["docker", "rm", "-f", self._container_name], check=False, timeout=30)
        command = (
            "set -eu\n"
            "zoekt-index -index /data/index /input >/dev/null\n"
            'printf \'{"started_at": %s}\\n\' "$(date +%s)" > /data/index/.atelier-zoekt-state.json\n'
            "exec zoekt-webserver -index /data/index -pprof -rpc\n"
        )
        completed = _run_command(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--ulimit",
                f"nofile={_DOCKER_NOFILE}",
                "--name",
                self._container_name,
                "-v",
                f"{self.input_root}:/input:ro",
                "-v",
                f"{self.index_root}:/data/index",
                resolution.image_ref,
                "sh",
                "-lc",
                command,
            ],
            timeout=120,
        )
        self._container_id = completed.stdout.strip()
        self._wait_for_container_ready()
        self._bridge = _start_bridge(self._container_id)
        self._started_at = self._load_started_at()

    def build_index(self, resolution: ZoektBinaryResolution) -> None:
        """Build or incrementally update the Zoekt index for this workspace.

        **Never call this on the MCP tool-call hot path.**  It is the
        indexing route: ``atelier code index``, ``atelier zoekt up``, and
        the benchmark prewarm script.  MCP search calls go through
        ``ensure_started()`` which only *registers* an existing index.

        For git repos ``zoekt-git-index`` is used: it stores indexed
        git-object hashes in each shard and automatically re-indexes only
        changed objects on subsequent runs, handling deletions correctly
        (no stale shard accumulation).  For non-git directories
        ``zoekt-index`` does a full rebuild.
        """
        search_binary, index_binary, git_index_binary = _resolve_host_binaries(resolution)
        self._prepare_runtime_dirs()
        self._refresh_input_links()

        is_git = (self.repo_root / ".git").exists()
        if git_index_binary is not None and is_git:
            # Inherently incremental: first run indexes everything; subsequent
            # runs diff against shard metadata and only touch changed objects.
            _run_command(
                [str(git_index_binary), "-index", str(self.index_root), str(self.repo_root)],
                timeout=300,
            )
        else:
            # No git-aware indexer available or non-git dir: full rebuild.
            _run_command(
                [str(index_binary), "-index", str(self.index_root), str(self.input_root)],
                timeout=300,
            )

        self.state_path.write_text(json.dumps({"started_at": int(time.time())}), encoding="utf-8")
        self._host_search_binary = search_binary

    def _prepare_runtime_dirs(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.index_root.mkdir(parents=True, exist_ok=True)
        self.input_root.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            self.runtime_root.chmod(0o700)
        with suppress(OSError):
            self.index_root.chmod(0o700)
        with suppress(OSError):
            self.input_root.chmod(0o700)

    def _refresh_input_links(self) -> None:
        shutil.rmtree(self.input_root, ignore_errors=True)
        self.input_root.mkdir(parents=True, exist_ok=True)
        for entry in sorted(self.repo_root.iterdir()):
            if entry.name in _SKIP_ROOTS or entry.name.startswith("."):
                continue
            _mirror_entry(entry, self.input_root / entry.name)

    def _wait_for_container_ready(self) -> None:
        if self._container_id is None:
            raise RuntimeError("Zoekt container did not start")
        deadline = time.time() + _STARTUP_TIMEOUT_SECONDS
        while time.time() < deadline:
            probe = _run_command(
                [
                    "docker",
                    "exec",
                    self._container_id,
                    "sh",
                    "-lc",
                    "wget -qO- http://127.0.0.1:6070/healthz >/dev/null || wget -qO- http://127.0.0.1:6070/ >/dev/null",
                ],
                check=False,
                timeout=10,
            )
            if probe.returncode == 0:
                return
            status = _run_command(
                ["docker", "inspect", "-f", "{{.State.Running}}", self._container_id], check=False, timeout=10
            )
            if status.returncode != 0 or status.stdout.strip() != "true":
                logs = _run_command(["docker", "logs", self._container_id], check=False, timeout=10)
                raise RuntimeError(
                    logs.stderr.strip() or logs.stdout.strip() or "zoekt container exited before becoming ready"
                )
            time.sleep(_POLL_INTERVAL_SECONDS)
        raise RuntimeError("zoekt container did not become ready in time")

    def _bridge_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        bridge = self._bridge
        if bridge is None or bridge.stdin is None or bridge.stdout is None:
            raise RuntimeError("zoekt bridge is not running")
        encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
        with self._request_lock:
            bridge.stdin.write(encoded + "\n")
            bridge.stdin.flush()
            # readline() can block forever if Docker or the webserver stalls.
            # A threading.Timer kills the bridge after 30 s, which makes
            # readline() return "" (EOF) so the loop exits cleanly.
            # We can't use select.select() here: Python's TextIOWrapper may
            # have already pulled the sentinel line into its internal buffer
            # from the same OS read as the JSON body, leaving the fd empty
            # and causing a spurious select timeout.
            timed_out = threading.Event()

            def _kill_bridge() -> None:
                timed_out.set()
                with suppress(Exception):
                    bridge.kill()
                # Reap the killed child and drop the handle so it is not left as a
                # zombie with leaked pipe fds, and so _is_ready() reads False
                # unambiguously for the now-dead bridge.
                with suppress(Exception):
                    bridge.wait(timeout=5)
                self._bridge = None

            response_lines: list[str] = []
            timer = threading.Timer(30.0, _kill_bridge)
            timer.start()
            try:
                while True:
                    line = bridge.stdout.readline()
                    if line == "":
                        if timed_out.is_set():
                            raise TimeoutError("zoekt bridge did not respond within 30 s")
                        stderr = ""
                        if bridge.stderr is not None:
                            with suppress(Exception):
                                stderr = bridge.stderr.read().strip()
                        raise RuntimeError(stderr or "zoekt bridge exited unexpectedly")
                    if line.rstrip("\n") == _BRIDGE_SENTINEL:
                        break
                    response_lines.append(line)
            finally:
                timer.cancel()
        body = "".join(response_lines).strip()
        if not body:
            raise RuntimeError("zoekt bridge returned an empty response")
        return cast(dict[str, Any], json.loads(body))

    def _run_host_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        search_binary = self._host_search_binary
        if search_binary is None:
            raise RuntimeError("zoekt host runtime is not initialized")
        query = str(payload.get("Q") or "")
        completed = _run_command(
            [str(search_binary), "-index_dir", str(self.index_root), "-jsonl", query],
            check=False,
            timeout=30,
        )
        if completed.returncode not in (0, 1):
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "zoekt search failed")
        files: list[dict[str, Any]] = []
        for raw_line in completed.stdout.splitlines():
            if not raw_line.strip():
                continue
            files.append(json.loads(raw_line))
        return {"Result": {"Files": files}}

    def _load_started_at(self) -> float | None:
        candidates = [self.index_root / ".atelier-zoekt-state.json", self.state_path]
        for path in candidates:
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            value = payload.get("started_at")
            if isinstance(value, (int, float)):
                return float(value)
        return None


def _resolve_host_binaries(resolution: ZoektBinaryResolution) -> tuple[Path, Path, Path | None]:
    """Return (search_binary, plain_index_binary, git_index_binary|None)."""
    if resolution.path is None:
        raise RuntimeError("zoekt host runtime is missing the pinned binary path")
    root = resolution.path.parent
    search_binary = resolution.path if resolution.path.name == "zoekt" else root / "zoekt"
    index_binary = root / "zoekt-index"
    git_index_binary = root / "zoekt-git-index"
    if not search_binary.is_file() or not os.access(search_binary, os.X_OK):
        raise RuntimeError(f"zoekt search binary is missing beside {resolution.path}")
    if not index_binary.is_file() or not os.access(index_binary, os.X_OK):
        raise RuntimeError(f"zoekt-index binary is missing beside {resolution.path}")
    git_idx = git_index_binary if git_index_binary.is_file() and os.access(git_index_binary, os.X_OK) else None
    return search_binary, index_binary, git_idx


def _run_command(
    command: list[str],
    *,
    check: bool = True,
    timeout: int | float = 60,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip() or completed.stdout.strip() or f"command failed: {' '.join(command)}"
        )
    return completed


def _mirror_entry(source: Path, target: Path) -> None:
    if not source.exists():
        return
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            for child in sorted(source.iterdir()):
                if child.name in _SKIP_ROOTS or child.name.startswith("."):
                    continue
                _mirror_entry(child, target / child.name)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = source.stat().st_mode
    except OSError:
        return
    try:
        if mode & 0o004:
            os.link(source, target)
            return
        raise OSError
    except OSError:
        shutil.copy2(source, target)
        with suppress(OSError):
            target.chmod(mode | 0o444)


def _start_bridge(container_id: str) -> subprocess.Popen[str]:
    script = (
        "set -eu\n"
        "while IFS= read -r encoded; do\n"
        "  printf '%s' \"$encoded\" | base64 -d > /tmp/atelier-zoekt-query.json\n"
        "  wget -qO- --header='Content-Type: application/json' "
        "--post-file=/tmp/atelier-zoekt-query.json http://127.0.0.1:6070/api/search\n"
        f"  printf '\\n{_BRIDGE_SENTINEL}\\n'\n"
        "done\n"
    )
    return subprocess.Popen(
        ["docker", "exec", "-i", container_id, "sh", "-lc", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


_SERVERS: dict[str, ZoektServer] = {}
_SERVERS_LOCK = threading.Lock()


def get_zoekt_server(repo_root: str | Path, *, resolution: ZoektBinaryResolution | None = None) -> ZoektServer:
    root = Path(repo_root).resolve()
    key = str(root)
    with _SERVERS_LOCK:
        server = _SERVERS.get(key)
        if server is None:
            server = ZoektServer(root, resolution=resolution)
            _SERVERS[key] = server
        elif resolution is not None and server.resolution is None:
            server.resolution = resolution
    return server


def reset_zoekt_servers() -> None:
    with _SERVERS_LOCK:
        servers = list(_SERVERS.values())
        _SERVERS.clear()
    for server in servers:
        server.stop()


atexit.register(reset_zoekt_servers)


__all__ = ["ZoektHealth", "ZoektServer", "get_zoekt_server", "reset_zoekt_servers"]
