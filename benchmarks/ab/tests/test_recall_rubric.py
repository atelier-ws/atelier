"""Tests for ab.graders.recall_rubric — LS-02."""

import json
import tempfile
from pathlib import Path

from ab.graders.recall_rubric import JUDGE_MODEL, JUDGE_VERSION, _build_prompt, grade_recall


def _mock_llm(score: float, notes: str = "ok"):
    def call(prompt: str, model: str) -> str:
        return json.dumps({"recall_score": score, "consistency_score": score, "notes": notes})

    return call


def test_judge_model_is_non_claude():
    """LS-02: judge model is pinned and non-Claude to avoid bias."""
    assert "gpt" in JUDGE_MODEL.lower() or "gemini" in JUDGE_MODEL.lower()
    assert "claude" not in JUDGE_MODEL.lower()


def test_judge_version_present():
    assert JUDGE_VERSION  # non-empty string


def test_grade_recall_returns_required_fields():
    """LS-02: grader returns judge_model, recall_score, consistency_score, etc."""
    with tempfile.TemporaryDirectory() as d:
        transcript = Path(d) / "transcript.json"
        transcript.write_text('{"turn": "final answer recalling project_name correctly"}')

        result = grade_recall(
            transcript,
            task_setup_facts=["project_name", "repo_url"],
            turn_cut=50,
            _llm_call=_mock_llm(0.8),
        )

    assert "recall_score" in result
    assert "consistency_score" in result
    assert "overall_quality" in result
    assert "verdict" in result
    assert "judge_model" in result
    assert result["judge_model"] == JUDGE_MODEL  # LS-02: stated in output


def test_grade_recall_pass_verdict_above_threshold():
    with tempfile.TemporaryDirectory() as d:
        transcript = Path(d) / "transcript.json"
        transcript.write_text("{}")
        result = grade_recall(
            transcript,
            task_setup_facts=["project_name"],
            turn_cut=50,
            _llm_call=_mock_llm(0.8),
        )
    assert result["verdict"] == "pass"
    assert result["overall_quality"] == 0.8


def test_grade_recall_fail_verdict_below_threshold():
    with tempfile.TemporaryDirectory() as d:
        transcript = Path(d) / "transcript.json"
        transcript.write_text("{}")
        result = grade_recall(
            transcript,
            task_setup_facts=["project_name"],
            turn_cut=100,
            _llm_call=_mock_llm(0.3),
        )
    assert result["verdict"] == "fail"


def test_grade_recall_handles_parse_error():
    """LS-02: grader handles malformed LLM output gracefully."""
    with tempfile.TemporaryDirectory() as d:
        transcript = Path(d) / "transcript.json"
        transcript.write_text("{}")

        def bad_llm(prompt: str, model: str) -> str:
            return "this is not json"

        result = grade_recall(
            transcript,
            task_setup_facts=["project_name"],
            turn_cut=50,
            _llm_call=bad_llm,
        )
    assert result["recall_score"] == 0.0
    assert "parse error" in result["notes"]
    assert result["verdict"] == "fail"


def test_build_prompt_contains_facts():
    prompt = _build_prompt(["project_name", "repo_url"], turn_cut=50, transcript_tail="tail")
    assert "project_name" in prompt
    assert "repo_url" in prompt
    assert "50" in prompt
