"""Benchmark cases for the public text-returning `shell` MCP tool.

Savings come from:
- ANSI stripping (no garbage tokens from terminal color codes)
- head+tail truncation (agent sees structure, not 10k lines of logs)
- Transparent rewrites: cat→read, rg/grep→grep (cheaper tools, better ranking)
- Compact text rendering: agent reads a concise result instead of raw process I/O

Baseline estimates:
  - echo/simple: raw subprocess + parse stdout (~80 tokens framing)
  - cat rewrite: cat would read raw file content; read tool is outline-first (~300 token baseline vs atelier)
  - rg rewrite: rg prints raw matches; grep tool returns ranked, budget-capped (~250 tokens baseline)
  - blocked: agent calls rm -rf, catches -1 exit; structured blocked=True makes it unambiguous
  - truncated: seq 1..500 without atelier would dump 500 lines; atelier caps at max_lines

SHELL_WORKSPACE env var injected by bench_shell.py.
"""

from __future__ import annotations

from benchmarks.mcp_tools.harness import BenchCase

# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def _as_text(result: object) -> str:
    assert isinstance(result, str), f"shell tool must return text, got: {type(result).__name__}"
    return result


def _assert_echo_content(result: object) -> None:
    text = _as_text(result)
    assert "bench_hello" in text, f"expected 'bench_hello' in output, got: {text!r}"


def _assert_cat_rewritten(result: object) -> None:
    text = _as_text(result)
    assert "sentinel_content" in text, f"cat rewrite must return file content, got: {text!r}"


def _assert_rg_rewritten(result: object) -> None:
    text = _as_text(result)
    assert "needle_token" in text, f"rewritten grep must find needle_token, got: {text!r}"
    assert "src/module.py" in text, f"rewritten grep must include the matching file, got: {text!r}"


def _assert_rg_type_rewritten(result: object) -> None:
    text = _as_text(result)
    assert "needle_token" in text, f"rg --type rewrite must find needle_token, got: {text!r}"
    assert "src/module.py" in text, (
        f"rg --type rewrite must include the matching file, got: {text!r}"
    )


def _assert_blocked_rm(result: object) -> None:
    text = _as_text(result)
    assert text.startswith("blocked (exit_code=-1)"), (
        f"blocked command must show exit_code=-1, got: {text!r}"
    )
    assert "Destructive rm -rf commands are blocked" in text, (
        f"blocked rm reason missing, got: {text!r}"
    )


def _assert_blocked_bash(result: object) -> None:
    text = _as_text(result)
    assert text.startswith("blocked (exit_code=-1)"), (
        f"blocked command must show exit_code=-1, got: {text!r}"
    )
    assert "Direct bash execution is blocked" in text, f"blocked bash reason missing, got: {text!r}"


def _assert_truncated(result: object) -> None:
    text = _as_text(result)
    assert "[output truncated:" in text, f"truncation marker missing, got: {text!r}"
    assert "lines omitted" in text, f"line omission marker missing, got: {text!r}"
    assert "1\n2\n3" in text, f"truncated output must keep head context, got: {text!r}"
    assert "498\n499\n500" in text, f"truncated output must keep tail context, got: {text!r}"


def _assert_exit_nonzero(result: object) -> None:
    text = _as_text(result)
    assert text.startswith("exit_code=1"), f"expected non-zero exit marker, got: {text!r}"


# ---------------------------------------------------------------------------
# Cases  (__SHELL_WORKSPACE__ is patched in by bench_shell.py)
# ---------------------------------------------------------------------------

SHELL_CASES: list[BenchCase] = [
    BenchCase(
        op="shell",
        label="shell/echo",
        args={"command": "echo bench_hello"},
        assert_keys=[],
        custom_assert=_assert_echo_content,
        # baseline: raw subprocess call + string framing
        baseline_tokens=80,
    ),
    BenchCase(
        op="shell",
        label="shell/cat-rewrite",
        args={"command": "cat __SHELL_FILE__"},
        assert_keys=[],
        custom_assert=_assert_cat_rewritten,
        # baseline: raw cat dumps entire file content to stdout without outline
        baseline_tokens=300,
    ),
    BenchCase(
        op="shell",
        label="shell/rg-rewrite",
        args={"command": "rg needle_token __SHELL_WORKSPACE__"},
        assert_keys=[],
        custom_assert=_assert_rg_rewritten,
        # baseline: rg prints raw match lines without budget cap
        baseline_tokens=250,
    ),
    BenchCase(
        op="shell",
        label="shell/rg-type-rewrite",
        args={"command": "rg --type py needle_token __SHELL_WORKSPACE__"},
        assert_keys=[],
        custom_assert=_assert_rg_type_rewritten,
        # baseline: same as rg rewrite
        baseline_tokens=250,
    ),
    BenchCase(
        op="shell",
        label="shell/blocked-rm",
        args={"command": "rm -rf /tmp/atelier_bench_never_runs"},
        assert_keys=[],
        custom_assert=_assert_blocked_rm,
        # correctness only — no savings baseline for blocked commands
        baseline_tokens=0,
    ),
    BenchCase(
        op="shell",
        label="shell/blocked-bash",
        args={"command": "bash -c 'echo no'"},
        assert_keys=[],
        custom_assert=_assert_blocked_bash,
        baseline_tokens=0,
    ),
    BenchCase(
        op="shell",
        label="shell/truncated-output",
        args={"command": "seq 1 500", "max_lines": 50},
        assert_keys=[],
        custom_assert=_assert_truncated,
        # baseline: 500 lines raw output vs 50 lines capped
        baseline_tokens=500,
    ),
    BenchCase(
        op="shell",
        label="shell/nonzero-exit",
        args={"command": "exit 1"},
        assert_keys=[],
        custom_assert=_assert_exit_nonzero,
        baseline_tokens=0,
    ),
]
