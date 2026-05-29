"""Benchmark execution runners backing the ``atelier benchmark`` CLI (QBL-CLI-03).

These functions hold the actual suite-execution logic (core runtime benchmark,
host-readiness verification, and installed-pack coverage) that previously lived
inline in ``gateway/cli/app.py``. The Click command callbacks in
``gateway/cli/commands/benchmark.py`` are thin wrappers that call these runners
and format the result; all business logic lives here.

Runners return plain ``dict`` payloads and raise domain errors (never
``click.ClickException``) so they stay usable outside the CLI.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _run_benchmark_core(
    *,
    root: Path,
    prompts: tuple[str, ...],
    model: str,
    rounds: int,
) -> dict[str, Any]:
    from atelier.infra.runtime.benchmarking import run_runtime_benchmark

    report = run_runtime_benchmark(root=root, prompts=prompts, model=model, rounds=rounds)
    return {"suite": "core", "report": report}


def _run_benchmark_hosts(*, workspace: str | None = None) -> dict[str, Any]:
    script = _repo_root() / "scripts" / "verify_agent_clis.sh"
    cmd = ["bash", str(script)]
    if workspace:
        cmd.extend(["--workspace", workspace])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    output = (proc.stdout or "") + (proc.stderr or "")
    return {
        "suite": "hosts",
        "exit_code": proc.returncode,
        "status": "pass" if proc.returncode == 0 else "fail",
        "command": " ".join(cmd),
        "output": output.strip(),
    }


def _run_benchmark_packs(*, root: Path, host: str) -> dict[str, Any]:
    from atelier.core.domains import DomainManager

    manager = DomainManager(root)
    bundle_ids = [ref.bundle_id for ref in manager.list_bundles()]

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for bundle_id in bundle_ids:
        try:
            info = manager.info(bundle_id) or {}
            results.append({"bundle_id": bundle_id, "domain": info.get("domain", ""), "status": "ok"})
        except Exception as exc:
            logging.exception("Recovered from broad exception handler")
            failures.append({"bundle_id": bundle_id, "error": str(exc)})

    return {
        "suite": "domains",
        "host": host,
        "domains_total": len(bundle_ids),
        "domains_benchmarked": len(results),
        "results": results,
        "failures": failures,
    }
