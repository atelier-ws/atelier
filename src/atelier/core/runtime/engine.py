"""Compounding reasoning runtime orchestration.

Coordinates core capabilities, rubrics, traces, evals, environments, and storage
from a single runtime entry point.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, ClassVar

from atelier.core.capabilities import (
    ContextCompressionCapability,
    LoopDetectionCapability,
    ReasoningReuseCapability,
    SemanticFileMemoryCapability,
    ToolSupervisionCapability,
)
from atelier.core.foundation.renderer import render_context_for_agent
from atelier.core.foundation.store import ReasoningStore
from atelier.infra.runtime.run_ledger import RunLedger


class AtelierRuntimeCore:
    """Single runtime orchestrator for Atelier core capabilities."""

    CAPABILITIES: ClassVar[dict[str, str]] = {
        "reasoning_reuse": "Reuse prior successful procedures and failure signatures.",
        "semantic_file_memory": "Semantic summaries and symbol maps for local files.",
        "loop_detection": "Repeated-failure and dead-end detection with runtime alerts.",
        "tool_supervision": "Redundancy detection, observation cache, and efficiency metrics.",
        "context_compression": "Compress stale history into actionable runtime context.",
    }

    def __init__(self, root: str | Path = ".atelier") -> None:
        self.root = Path(root)
        self.store = ReasoningStore(self.root)
        self.store.init()

        self.reasoning_reuse = ReasoningReuseCapability(self.store, self.root)
        self.semantic_memory = SemanticFileMemoryCapability(self.root)
        self.loop_detection = LoopDetectionCapability()
        self.tool_supervision = ToolSupervisionCapability(self.root)
        self.context_compression = ContextCompressionCapability()

    def capability_list(self) -> list[dict[str, str]]:
        return [
            {"id": key, "description": value}
            for key, value in sorted(self.CAPABILITIES.items(), key=lambda item: item[0])
        ]

    def capability_status(self) -> dict[str, Any]:
        return {
            "capabilities": self.capability_list(),
            "tool_supervision": self.tool_supervision.status(),
            "semantic_entries": len(self.semantic_memory._load().get("files", {})),
        }

    def get_reasoning_context(
        self,
        *,
        task: str,
        domain: str | None = None,
        files: list[str] | None = None,
        tools: list[str] | None = None,
        errors: list[str] | None = None,
        max_blocks: int = 5,
    ) -> str:
        scored = self.reasoning_reuse.retrieve(
            task=task,
            domain=domain,
            files=files,
            tools=tools,
            errors=errors,
            limit=max_blocks,
        )
        return render_context_for_agent([item.block for item in scored])

    def smart_search(self, query: str, *, limit: int = 10) -> dict[str, Any]:
        query = query.strip()
        if not query:
            return {"matches": [], "semantic": []}

        cache_key = f"smart-search:{query}:{limit}"
        cached = self.tool_supervision.get(cache_key)
        if cached is not None:
            self.tool_supervision.observe(cache_key, cached, cache_hit=True)
            return {"cached": True, **cached}

        block_matches = self.store.search_blocks(query, limit=limit)
        semantic_matches = self.semantic_memory.semantic_search(query, limit=limit)
        payload = {
            "matches": [
                {"id": block.id, "title": block.title, "domain": block.domain}
                for block in block_matches
            ],
            "semantic": semantic_matches,
        }
        self.tool_supervision.observe(cache_key, payload, cache_hit=False)
        return {"cached": False, **payload}

    def smart_read(self, path: str | Path, *, max_lines: int = 120) -> dict[str, Any]:
        file_path = Path(path)
        cache_key = f"smart-read:{file_path.resolve()}:{max_lines}"

        cached_summary = self.semantic_memory.get_cached(file_path)
        if cached_summary is not None:
            payload = {
                "path": cached_summary.path,
                "summary": cached_summary.summary,
                "language": cached_summary.language,
                "symbols": cached_summary.symbols,
                "exports": cached_summary.exports,
                "lines_total": cached_summary.lines_total,
                "ast_summary": cached_summary.ast_summary,
            }
            self.tool_supervision.observe(cache_key, payload, cache_hit=True)
            return {"cached": True, **payload}

        summary = self.semantic_memory.summarize_file(file_path, max_lines=max_lines)
        payload = {
            "path": summary.path,
            "summary": summary.summary,
            "language": summary.language,
            "symbols": summary.symbols,
            "exports": summary.exports,
            "lines_total": summary.lines_total,
            "ast_summary": summary.ast_summary,
        }
        self.tool_supervision.observe(cache_key, payload, cache_hit=False)
        return {"cached": False, **payload}

    def smart_edit(self, edits: list[dict[str, str]]) -> dict[str, Any]:
        applied = 0
        failed: list[dict[str, str]] = []

        for item in edits:
            path = Path(item.get("path", ""))
            find = item.get("find", "")
            replace = item.get("replace", "")
            if not path.is_file():
                failed.append({"path": str(path), "error": "file-not-found"})
                continue

            text = path.read_text(encoding="utf-8", errors="replace")
            if find not in text:
                failed.append({"path": str(path), "error": "pattern-not-found"})
                continue

            updated = text.replace(find, replace)
            path.write_text(updated, encoding="utf-8")
            applied += 1

        cache_key = f"smart-edit:{applied}:{len(failed)}"
        payload = {"applied": applied, "failed": failed}
        self.tool_supervision.observe(cache_key, payload, cache_hit=False)
        return payload

    def sql_inspect(
        self, *, sql: str | None = None, file_path: str | None = None
    ) -> dict[str, Any]:
        source = sql
        if source is None and file_path:
            p = Path(file_path)
            if not p.is_file():
                raise FileNotFoundError(f"file not found: {file_path}")
            source = p.read_text(encoding="utf-8", errors="replace")

        if source is None:
            raise ValueError("provide sql text or file_path")

        tables = sorted(
            set(re.findall(r"\b(?:from|join|update|into)\s+([a-zA-Z0-9_.]+)", source, re.I))
        )
        fks = re.findall(
            r"\bforeign\s+key\s*\(([^)]+)\)\s*references\s+([a-zA-Z0-9_.]+)\s*\(([^)]+)\)",
            source,
            re.I,
        )

        select_count = len(re.findall(r"\bselect\b", source, re.I))
        join_count = len(re.findall(r"\bjoin\b", source, re.I))
        mutation_count = len(
            re.findall(r"\b(insert|update|delete|alter|create|drop)\b", source, re.I)
        )

        return {
            "tables": tables,
            "foreign_keys": [
                {
                    "local_columns": local_cols.strip(),
                    "references_table": table.strip(),
                    "references_columns": ref_cols.strip(),
                }
                for local_cols, table, ref_cols in fks
            ],
            "query_profile": {
                "select_count": select_count,
                "join_count": join_count,
                "mutation_count": mutation_count,
            },
            "migration_awareness": {
                "contains_alter_table": bool(re.search(r"\balter\s+table\b", source, re.I)),
                "contains_create_table": bool(re.search(r"\bcreate\s+table\b", source, re.I)),
            },
        }

    def summarize_memory(self, run_id: str | None = None) -> dict[str, Any]:
        if run_id:
            ledger_path = self.root / "runs" / f"{run_id}.json"
        else:
            runs_dir = self.root / "runs"
            paths = sorted(runs_dir.glob("*.json")) if runs_dir.is_dir() else []
            if not paths:
                raise FileNotFoundError("no run ledgers available")
            ledger_path = paths[-1]

        ledger = RunLedger.load(ledger_path)
        compressed = self.context_compression.compress(ledger)
        loops = self.loop_detection.from_ledger(ledger)
        compressed["loop_alerts"] = loops
        compressed["run_id"] = ledger.run_id
        return compressed

    def benchmark_runtime_metrics(self) -> dict[str, Any]:
        supervision = self.tool_supervision.status()
        memory_state = self.semantic_memory._load()
        return {
            "total_tool_calls": supervision["total_tool_calls"],
            "avoided_tool_calls": supervision["avoided_tool_calls"],
            "retries_prevented": supervision["retries_prevented"],
            "token_savings": supervision["avoided_tool_calls"] * 200,
            "loops_prevented": supervision["retries_prevented"],
            "successful_rescues": len(memory_state.get("files", {})),
            "validation_catches": 0,
            "context_reduction": 0,
            "task_success_rate": 0.0,
        }

    def export_benchmark_runtime(self, output: Path) -> Path:
        payload = self.benchmark_runtime_metrics()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return output

    # ------------------------------------------------------------------ #
    # Semantic file memory helpers                                         #
    # ------------------------------------------------------------------ #

    def module_summary(self, path: str | Path) -> dict[str, Any]:
        """Return a concise module-level summary: exports, symbols, imports."""
        return self.semantic_memory.module_summary(path)

    def symbol_search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Search all cached files for symbols matching query."""
        return self.semantic_memory.symbol_search(query, limit=limit)

    # ------------------------------------------------------------------ #
    # Loop detection helpers                                               #
    # ------------------------------------------------------------------ #

    def detect_loop(self, ledger: RunLedger) -> dict[str, Any]:
        """Run full loop analysis on a ledger and return the report dict."""
        report = self.loop_detection.check(ledger)
        return report.to_dict()

    def loop_report(self, run_id: str | None = None) -> dict[str, Any]:
        """Load the ledger and return a loop analysis report."""
        ledger = self._load_ledger(run_id)
        return self.detect_loop(ledger)

    # ------------------------------------------------------------------ #
    # Tool supervision helpers                                             #
    # ------------------------------------------------------------------ #

    def tool_report(self) -> dict[str, Any]:
        """Return human-readable tool usage + savings summary."""
        return self.tool_supervision.tool_report()

    def diff_context(self, paths: list[str], *, lines: int = 5) -> dict[str, Any]:
        """Return unified diff context for the given paths (git diff HEAD)."""
        return self.tool_supervision.diff_context(paths, lines=lines)

    def test_context(self, paths: list[str]) -> dict[str, Any]:
        """Return test files related to the given source files."""
        return self.tool_supervision.test_context(paths)

    # ------------------------------------------------------------------ #
    # Context compression helpers                                          #
    # ------------------------------------------------------------------ #

    def context_report(self, run_id: str | None = None) -> dict[str, Any]:
        """Return compression + provenance report for a run."""
        ledger = self._load_ledger(run_id)
        return self.context_compression.context_report(ledger)

    # ------------------------------------------------------------------ #
    # Inject runtime reasoning                                             #
    # ------------------------------------------------------------------ #

    def inject_reasoning(
        self,
        *,
        task: str,
        domain: str | None = None,
        files: list[str] | None = None,
        tools: list[str] | None = None,
        errors: list[str] | None = None,
        max_blocks: int = 5,
    ) -> dict[str, Any]:
        """Return full inject_runtime_reasoning payload."""
        return self.reasoning_reuse.inject_runtime_reasoning(
            task=task,
            domain=domain,
            files=files,
            tools=tools,
            errors=errors,
            max_blocks=max_blocks,
        )

    # ------------------------------------------------------------------ #
    # Lifecycle hooks (AtelierRuntimeV3)                                   #
    # ------------------------------------------------------------------ #

    def pre_plan(
        self,
        plan: list[str],
        *,
        domain: str | None = None,
        task: str = "",
    ) -> dict[str, Any]:
        """Hook: called before executing a plan.

        Returns reasoning context and any loop/dead-end warnings.
        """
        reasoning = self.inject_reasoning(task=task, domain=domain)
        return {
            "hook": "pre_plan",
            "procedures": reasoning.get("procedures", []),
            "dead_ends": reasoning.get("dead_ends", []),
            "rescue_strategies": reasoning.get("rescue_strategies", []),
            "plan_step_count": len(plan),
        }

    def pre_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        ledger: RunLedger | None = None,
    ) -> dict[str, Any]:
        """Hook: called before a tool invocation.

        Checks for loop conditions and returns cached result if available.
        """
        args_key = f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)[:100]}"
        cached = self.tool_supervision.get(args_key)
        loop_alert: dict[str, Any] | None = None
        if ledger is not None:
            report = self.loop_detection.check(ledger)
            if report.loop_detected:
                loop_alert = {
                    "severity": report.severity,
                    "summary": f"Loop detected: {', '.join(report.loop_types)}",
                    "rescue": report.rescue_strategies[:1],
                }
        return {
            "hook": "pre_tool",
            "tool": tool_name,
            "cached_result": cached,
            "cache_available": cached is not None,
            "loop_alert": loop_alert,
        }

    def post_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        *,
        output_chars: int = 0,
    ) -> None:
        """Hook: record tool observation after invocation."""
        args_key = f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)[:100]}"
        payload = dict(result)
        payload["output_chars"] = output_chars
        self.tool_supervision.observe(args_key, payload, cache_hit=False)

    def pre_patch(
        self,
        files: list[str],
        diff: str = "",
    ) -> dict[str, Any]:
        """Hook: called before applying a patch.

        Returns safety info from loop detection + file summaries.
        """
        summaries: list[dict[str, Any]] = []
        for path in files:
            try:
                summaries.append(self.module_summary(path))
            except (FileNotFoundError, OSError):
                summaries.append({"path": path, "error": "file-not-found"})
        return {
            "hook": "pre_patch",
            "files": files,
            "file_summaries": summaries,
            "diff_preview": diff[:500] if diff else "",
        }

    def post_patch(
        self,
        files: list[str],
        result: dict[str, Any],
    ) -> None:
        """Hook: invalidate semantic memory cache after patch."""
        for path in files:
            # Re-summarize to update cache
            import contextlib

            with contextlib.suppress(FileNotFoundError, OSError):
                self.semantic_memory.summarize_file(path)

    def pre_validation(
        self,
        checks: list[str],
        *,
        rubric_id: str | None = None,
    ) -> dict[str, Any]:
        """Hook: gather context before running validation rubric."""
        reasoning = self.inject_reasoning(
            task=f"validation:{rubric_id or 'unknown'}",
        )
        return {
            "hook": "pre_validation",
            "checks": checks,
            "rubric_id": rubric_id,
            "rescue_strategies": reasoning.get("rescue_strategies", []),
        }

    def post_validation(self, result: dict[str, Any]) -> None:
        """Hook: record validation outcome (no-op unless extended)."""
        pass  # Extend to record pass/fail in ledger

    def finalize(self, *, status: str = "completed") -> dict[str, Any]:
        """Hook: produce final run summary with aggregate savings."""
        supervision = self.tool_supervision.status()
        memory_state = self.semantic_memory._load()
        files_cached = len(memory_state.get("files", {}))
        return {
            "hook": "finalize",
            "status": status,
            "savings": {
                "total_tool_calls": supervision["total_tool_calls"],
                "avoided_tool_calls": supervision["avoided_tool_calls"],
                "token_savings": supervision["token_savings"],
                "chars_saved": supervision["chars_saved"],
                "retries_prevented": supervision["retries_prevented"],
            },
            "semantic_cache_size": files_cached,
        }

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _load_ledger(self, run_id: str | None = None) -> RunLedger:
        if run_id:
            ledger_path = self.root / "runs" / f"{run_id}.json"
        else:
            runs_dir = self.root / "runs"
            paths = sorted(runs_dir.glob("*.json")) if runs_dir.is_dir() else []
            if not paths:
                raise FileNotFoundError("no run ledgers available")
            ledger_path = paths[-1]
        return RunLedger.load(ledger_path)


# Alias for the V3 lifecycle-enabled runtime
AtelierRuntimeV3 = AtelierRuntimeCore
