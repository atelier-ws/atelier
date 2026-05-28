"""Recall-rubric grader using LLM-as-judge — LS-02.

Grades fact recall and consistency from a long-session transcript.
Judge model is pinned (non-Claude to avoid self-serving bias) and
stated in every report (LS-02 requirement).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# LS-02: pinned non-Claude judge to avoid bias — stated in reports
JUDGE_MODEL = "gpt-4o-2024-11-20"
JUDGE_VERSION = "1"

_RECALL_PROMPT_TEMPLATE = """\
You are evaluating an AI assistant's long-session memory performance.

The assistant was seeded with these facts at the start of the session:
{facts_json}

Below is the final turn of the conversation (turn ~{turn_cut}):
<transcript_tail>
{transcript_tail}
</transcript_tail>

Score the assistant on two dimensions (0.0-1.0 each):
1. recall_score: Did the assistant correctly recall the seeded facts when asked?
2. consistency_score: Were the assistant's answers consistent with earlier turns?

Respond ONLY with valid JSON:
{{"recall_score": <float>, "consistency_score": <float>, "notes": "<brief explanation>"}}
"""


def _build_prompt(task_setup_facts: list[str], turn_cut: int, transcript_tail: str) -> str:
    facts_json = json.dumps({k: f"<value-for-{k}>" for k in task_setup_facts}, indent=2)
    return _RECALL_PROMPT_TEMPLATE.format(
        facts_json=facts_json,
        turn_cut=turn_cut,
        transcript_tail=transcript_tail[:4000],
    )


def grade_recall(
    transcript_path: Path,
    task_setup_facts: list[str],
    turn_cut: int,
    judge_model: str = JUDGE_MODEL,
    *,
    _llm_call: Any = None,  # injectable for testing / mocking
) -> dict[str, Any]:
    """Grade recall quality for one long-session transcript (LS-02).

    Returns a dict with recall_score, consistency_score, overall_quality,
    verdict, judge_model (LS-02: pinned + stated in output), and notes.
    """
    # Load transcript tail (last 2000 chars or full content if short)
    transcript_text = transcript_path.read_text(errors="replace") if transcript_path.exists() else ""
    tail = transcript_text[-2000:] if len(transcript_text) > 2000 else transcript_text

    prompt = _build_prompt(task_setup_facts, turn_cut, tail)

    if _llm_call is not None:
        raw = _llm_call(prompt, judge_model)
    else:
        raw = _default_llm_call(prompt, judge_model)

    try:
        parsed = json.loads(raw)
        recall = float(parsed.get("recall_score", 0.0))
        consistency = float(parsed.get("consistency_score", 0.0))
        notes = str(parsed.get("notes", ""))
    except (json.JSONDecodeError, ValueError):
        recall, consistency, notes = 0.0, 0.0, f"parse error: {raw[:200]}"

    overall = round((recall + consistency) / 2, 4)
    verdict = "pass" if overall >= 0.5 else "fail"

    return {
        "task_setup_facts": task_setup_facts,
        "turn_cut": turn_cut,
        "recall_score": recall,
        "consistency_score": consistency,
        "overall_quality": overall,
        "verdict": verdict,
        "judge_model": judge_model,  # LS-02: stated in every report
        "judge_version": JUDGE_VERSION,
        "notes": notes,
    }


def _default_llm_call(prompt: str, model: str) -> str:
    """Real LLM call via openai SDK (requires OPENAI_API_KEY)."""
    try:
        import openai  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("openai package required for recall grader. Install with: pip install openai") from exc

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=256,
    )
    return response.choices[0].message.content or ""
