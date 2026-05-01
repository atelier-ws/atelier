"""Extractor — produce a candidate ReasonBlock from a recorded trace.

Heuristic, not LLM-based. The output is always a *candidate* — humans (or
a future auto-rule) decide whether to accept it.

Confidence formula:
    base = 0.40
    + 0.20 if status == "success"
    + 0.10 per validation result that passed (cap 0.20)
    + 0.10 if at least one repeated_failure was overcome
    + 0.10 if both files_touched and validation_results are non-empty
"""

from __future__ import annotations

from dataclasses import dataclass

from atelier.core.foundation.models import ReasonBlock, Trace, slugify


@dataclass
class CandidateBlock:
    block: ReasonBlock
    confidence: float
    reasons: list[str]


def extract_candidate(trace: Trace) -> CandidateBlock:
    title = _derive_title(trace)
    domain = trace.domain or "coding"
    block_id = ReasonBlock.make_id(title, domain)

    dead_ends = _derive_dead_ends(trace)
    procedure = _derive_procedure(trace)
    verification = _derive_verification(trace)
    failure_signals = list({_short(e) for e in trace.errors_seen if e})[:8]

    confidence, reasons = _score_confidence(trace)

    block = ReasonBlock(
        id=block_id,
        title=title,
        domain=domain,
        task_types=[slugify(domain)],
        triggers=_derive_triggers(trace),
        file_patterns=_derive_file_patterns(trace),
        tool_patterns=_derive_tool_patterns(trace),
        situation=_derive_situation(trace),
        dead_ends=dead_ends,
        procedure=procedure or ["(procedure could not be extracted; manual edit required)"],
        verification=verification,
        failure_signals=failure_signals,
        when_not_to_apply="",
        status="active",
    )
    return CandidateBlock(block=block, confidence=confidence, reasons=reasons)


# --------------------------------------------------------------------------- #
# Derivations                                                                 #
# --------------------------------------------------------------------------- #


def _derive_title(trace: Trace) -> str:
    base = trace.task.strip().rstrip(".")
    if len(base) > 80:
        base = base[:77] + "..."
    return base or "Untitled procedure"


def _derive_situation(trace: Trace) -> str:
    if trace.diff_summary:
        return f"When working on: {trace.task}. Context: {trace.diff_summary}"
    return f"When working on: {trace.task}"


def _derive_triggers(trace: Trace) -> list[str]:
    triggers: list[str] = []
    for word in trace.task.split():
        if len(word) > 3 and word.isalpha():
            triggers.append(word.lower())
    return list(dict.fromkeys(triggers))[:10]


def _derive_file_patterns(trace: Trace) -> list[str]:
    out: list[str] = []
    for f in trace.files_touched:
        parts = f.split("/")
        pattern = "/".join(parts[:-1]) + "/**" if len(parts) >= 2 else parts[0]
        if pattern not in out:
            out.append(pattern)
    return out[:8]


def _derive_tool_patterns(trace: Trace) -> list[str]:
    return list(dict.fromkeys(t.name for t in trace.tools_called))[:8]


def _derive_dead_ends(trace: Trace) -> list[str]:
    dead: list[str] = []
    for rf in trace.repeated_failures:
        dead.append(f"Repeated failure pattern: {rf.signature}")
    return dead[:5]


def _derive_procedure(trace: Trace) -> list[str]:
    """Best-effort procedure derivation from successful actions."""
    steps: list[str] = []
    if trace.diff_summary:
        steps.append(f"Apply change: {trace.diff_summary}")
    for cmd in trace.commands_run:
        steps.append(f"Run: {cmd}")
    if trace.output_summary:
        steps.append(f"Confirm: {trace.output_summary}")
    return steps[:8]


def _derive_verification(trace: Trace) -> list[str]:
    out: list[str] = []
    for v in trace.validation_results:
        if v.passed:
            out.append(v.name)
    return out[:8]


def _short(text: str, n: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 3] + "..."


def _score_confidence(trace: Trace) -> tuple[float, list[str]]:
    score = 0.40
    reasons = ["base score 0.40"]
    if trace.status == "success":
        score += 0.20
        reasons.append("trace status = success (+0.20)")
    passed = sum(1 for v in trace.validation_results if v.passed)
    val_bonus = min(0.20, 0.10 * passed)
    if val_bonus:
        score += val_bonus
        reasons.append(f"{passed} validations passed (+{val_bonus:.2f})")
    if trace.repeated_failures and trace.status == "success":
        score += 0.10
        reasons.append("recovered from repeated failure (+0.10)")
    if trace.files_touched and trace.validation_results:
        score += 0.10
        reasons.append("both files touched and validations present (+0.10)")
    return min(1.0, score), reasons
