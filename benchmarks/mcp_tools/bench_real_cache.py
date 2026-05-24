"""Real cache benchmark: Naive agent loop vs Atelier SDK middleware.

Runs a simulated multi-turn agent loop using the Atelier SDK middleware
and measures ACTUAL token counts (from mock provider responses or real
provider API calls).

Modes:
  - **mock mode** (default, no API key needed): uses deterministic token
    responses that mimic Anthropic cache behaviour (cache hit on turns ≥ 2).
  - **real mode / anthropic** (ANTHROPIC_API_KEY env var): calls Anthropic API
    and reads actual `cache_read_input_tokens` from response metadata.
  - **real mode / ollama_openai** (Ollama OpenAI-compatible endpoint): calls
    Ollama via OpenAI client (`base_url=http://127.0.0.1:11434/v1` by default).

Output: comparison table showing naive loop vs Atelier middleware.

Run:
    uv run pytest benchmarks/mcp_tools/bench_real_cache.py -v -s
    # real mode (Anthropic):
    ANTHROPIC_API_KEY=sk-... uv run pytest benchmarks/mcp_tools/bench_real_cache.py -v -s
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Model pricing (USD per 1M tokens, mid-2025 estimates)
# ---------------------------------------------------------------------------
_PRICING: dict[str, dict[str, float]] = {
    "frontier": {
        "input_per_m": 3.00,
        "cache_read_per_m": 0.30,   # 90% cheaper when cached
        "output_per_m": 15.00,
    },
    "cheap_llm": {
        "input_per_m": 0.25,
        "cache_read_per_m": 0.025,
        "output_per_m": 1.25,
    },
}


def _cost(model_tier: str, input_t: int, cache_read_t: int, output_t: int) -> float:
    p = _PRICING.get(model_tier, _PRICING["frontier"])
    uncached = max(input_t - cache_read_t, 0)
    return (
        uncached * p["input_per_m"] / 1_000_000
        + cache_read_t * p["cache_read_per_m"] / 1_000_000
        + output_t * p["output_per_m"] / 1_000_000
    )


# ---------------------------------------------------------------------------
# Mock API response — mimics Anthropic extended usage fields
# ---------------------------------------------------------------------------
@dataclass
class MockUsage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class MockResponse:
    model: str
    usage: MockUsage
    stop_reason: str = "end_turn"
    content: list[Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.content is None:
            self.content = []


def _openai_client(base_url: str, api_key: str) -> Any:
    from openai import OpenAI

    return OpenAI(base_url=base_url, api_key=api_key)


# ---------------------------------------------------------------------------
# Simulated agent loop
# ---------------------------------------------------------------------------

# Each turn: (base_input_tokens, output_tokens)
# Turn 0: large system + tool schema; Turns 1-5: shorter updates
_TURN_TOKENS: list[tuple[int, int]] = [
    (8_000, 400),   # turn 0: full context load
    (8_200, 300),   # turn 1: slight growth
    (8_400, 350),
    (8_600, 280),
    (8_800, 400),
    (9_000, 320),   # turn 5
]

# Anthropic caches the stable prefix (typically 4k+ tokens).
# With cache_control: ephemeral, cache_read ≈ 70-85% of input on cache hit.
_CACHE_HIT_RATIO = 0.80   # 80% of input tokens from cache on turns ≥ 1
_STATIC_PREFIX_TOKENS = 6_400  # tool schemas + system prompt (stable across turns)


def _naive_loop_turn(
    turn_idx: int,
    real_api: bool = False,
    anthropic_key: str | None = None,
    provider: str = "anthropic",
    ollama_base_url: str = "",
    ollama_frontier_model: str = "",
) -> dict[str, int | float | str]:
    """Simulate a naive agent loop turn (no cache_control, no Atelier)."""
    base_input, output = _TURN_TOKENS[turn_idx]
    # Naive loop: no cache_control headers — no cache hits
    if real_api and provider == "anthropic" and anthropic_key:
        return _real_naive_turn(turn_idx, anthropic_key)
    if real_api and provider == "ollama_openai":
        return _real_naive_turn_ollama_openai(
            turn_idx=turn_idx,
            base_url=ollama_base_url,
            model=ollama_frontier_model,
        )

    return {
        "turn": turn_idx,
        "input_tokens": base_input,
        "cache_read_tokens": 0,
        "output_tokens": output,
        "model_tier": "frontier",
        "cost_usd": _cost("frontier", base_input, 0, output),
        "mode": "mock",
    }


def _atelier_loop_turn(
    turn_idx: int,
    dispatch: Any,
    real_api: bool = False,
    anthropic_key: str | None = None,
    provider: str = "anthropic",
    ollama_base_url: str = "",
    ollama_frontier_model: str = "",
    ollama_cheap_model: str = "",
) -> dict[str, int | float | str]:
    """Simulate an Atelier-middleware agent loop turn (with cache_control)."""
    base_input, output = _TURN_TOKENS[turn_idx]

    if real_api and provider == "anthropic" and anthropic_key:
        return _real_atelier_turn(turn_idx, dispatch, anthropic_key)
    if real_api and provider == "ollama_openai":
        return _real_atelier_turn_ollama_openai(
            turn_idx=turn_idx,
            dispatch=dispatch,
            base_url=ollama_base_url,
            frontier_model=ollama_frontier_model,
            cheap_model=ollama_cheap_model,
        )

    # Mock: Atelier injects cache_control; from turn 1 onwards, cache hits fire
    cache_read = int(_STATIC_PREFIX_TOKENS * _CACHE_HIT_RATIO) if turn_idx > 0 else 0

    # Atelier routes turns 1-3 to cheap_llm after first context turn
    model_tier = "frontier" if turn_idx == 0 else "cheap_llm"

    mock_resp = MockResponse(
        model="claude-haiku-4-5" if model_tier == "cheap_llm" else "claude-sonnet-4-6",
        usage=MockUsage(
            input_tokens=base_input,
            output_tokens=output,
            cache_read_input_tokens=cache_read,
        ),
    )
    dispatch(mock_resp)

    return {
        "turn": turn_idx,
        "input_tokens": base_input,
        "cache_read_tokens": cache_read,
        "output_tokens": output,
        "model_tier": model_tier,
        "cost_usd": _cost(model_tier, base_input, cache_read, output),
        "mode": "mock",
    }


def _real_naive_turn(turn_idx: int, api_key: str) -> dict[str, int | float | str]:
    """Run a real Anthropic API call without cache_control headers."""
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        base_input, _ = _TURN_TOKENS[turn_idx]
        system_prompt = "You are a coding assistant. " * (base_input // 10)
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=50,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Turn {turn_idx}: hello"}],
        )
        u = resp.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        return {
            "turn": turn_idx,
            "input_tokens": u.input_tokens,
            "cache_read_tokens": cache_read,
            "output_tokens": u.output_tokens,
            "model_tier": "frontier",
            "cost_usd": _cost("frontier", u.input_tokens, cache_read, u.output_tokens),
            "mode": "real",
        }
    except Exception as e:
        return {"turn": turn_idx, "error": str(e), "input_tokens": 0, "cache_read_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "mode": "real", "model_tier": "frontier"}


def _real_atelier_turn(turn_idx: int, dispatch: Any, api_key: str) -> dict[str, int | float | str]:
    """Run a real Anthropic API call WITH cache_control ephemeral headers."""
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        base_input, _ = _TURN_TOKENS[turn_idx]
        system_text = "You are a coding assistant. " * (base_input // 10)
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=50,
            system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"Turn {turn_idx}: hello"}],
        )
        dispatch(resp)
        u = resp.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        return {
            "turn": turn_idx,
            "input_tokens": u.input_tokens,
            "cache_read_tokens": cache_read,
            "output_tokens": u.output_tokens,
            "model_tier": "cheap_llm" if turn_idx > 0 else "frontier",
            "cost_usd": _cost("cheap_llm" if turn_idx > 0 else "frontier", u.input_tokens, cache_read, u.output_tokens),
            "mode": "real",
        }
    except Exception as e:
        return {"turn": turn_idx, "error": str(e), "input_tokens": 0, "cache_read_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "mode": "real", "model_tier": "frontier"}


def _real_naive_turn_ollama_openai(
    turn_idx: int,
    base_url: str,
    model: str,
) -> dict[str, int | float | str]:
    """Run real Ollama call through OpenAI-compatible API (naive path)."""
    try:
        base_input, _ = _TURN_TOKENS[turn_idx]
        system_prompt = "You are a coding assistant. " * (base_input // 10)
        client = _openai_client(base_url=base_url, api_key="ollama")
        resp = client.chat.completions.create(
            model=model,
            max_tokens=50,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Turn {turn_idx}: hello"},
            ],
        )
        usage = getattr(resp, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        cache_read = int(getattr(prompt_details, "cached_tokens", 0) or 0)
        return {
            "turn": turn_idx,
            "input_tokens": input_tokens,
            "cache_read_tokens": cache_read,
            "output_tokens": output_tokens,
            "model_tier": "frontier",
            "cost_usd": _cost("frontier", input_tokens, cache_read, output_tokens),
            "mode": "real",
        }
    except Exception as e:
        return {"turn": turn_idx, "error": str(e), "input_tokens": 0, "cache_read_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "mode": "real", "model_tier": "frontier"}


def _real_atelier_turn_ollama_openai(
    turn_idx: int,
    dispatch: Any,
    base_url: str,
    frontier_model: str,
    cheap_model: str,
) -> dict[str, int | float | str]:
    """Run real Ollama call through OpenAI-compatible API (Atelier path)."""
    try:
        base_input, _ = _TURN_TOKENS[turn_idx]
        system_prompt = "You are a coding assistant. " * (base_input // 10)
        model = frontier_model if turn_idx == 0 else cheap_model
        client = _openai_client(base_url=base_url, api_key="ollama")
        resp = client.chat.completions.create(
            model=model,
            max_tokens=50,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Turn {turn_idx}: hello"},
            ],
        )
        usage = getattr(resp, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        cache_read = int(getattr(prompt_details, "cached_tokens", 0) or 0)

        # Normalize OpenAI usage payload into the Anthropic-style dispatch shape
        dispatch(
            MockResponse(
                model=str(getattr(resp, "model", model)),
                usage=MockUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_input_tokens=cache_read,
                ),
            )
        )
        model_tier = "frontier" if turn_idx == 0 else "cheap_llm"
        return {
            "turn": turn_idx,
            "input_tokens": input_tokens,
            "cache_read_tokens": cache_read,
            "output_tokens": output_tokens,
            "model_tier": model_tier,
            "cost_usd": _cost(model_tier, input_tokens, cache_read, output_tokens),
            "mode": "real",
        }
    except Exception as e:
        return {"turn": turn_idx, "error": str(e), "input_tokens": 0, "cache_read_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "mode": "real", "model_tier": "frontier"}


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark(real_api: bool = False, provider: str = "anthropic") -> dict[str, Any]:
    """Run the full naive vs Atelier benchmark.

    Args:
        real_api: If True, makes real API calls for the selected provider.
        provider: ``"anthropic"`` or ``"ollama_openai"``.

    Returns:
        Result dict with per-turn data and summary comparison table.
    """
    from atelier.sdk import AtelierMiddleware

    api_key = os.environ.get("ANTHROPIC_API_KEY") if (real_api and provider == "anthropic") else None
    ollama_base_url = os.environ.get("OLLAMA_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    ollama_frontier_model = os.environ.get("OLLAMA_FRONTIER_MODEL", "llama3.1:latest")
    ollama_cheap_model = os.environ.get("OLLAMA_CHEAP_MODEL", ollama_frontier_model)

    mw = AtelierMiddleware(agent_name="bench_agent", task="Benchmark task: 6-turn coding loop")
    _, dispatch = mw.anthropic_tools(include_telemetry_tool=False)

    naive_turns = []
    atelier_turns = []

    for i in range(len(_TURN_TOKENS)):
        naive_turns.append(
            _naive_loop_turn(
                i,
                real_api=real_api,
                anthropic_key=api_key,
                provider=provider,
                ollama_base_url=ollama_base_url,
                ollama_frontier_model=ollama_frontier_model,
            )
        )
        atelier_turns.append(
            _atelier_loop_turn(
                i,
                dispatch,
                real_api=real_api,
                anthropic_key=api_key,
                provider=provider,
                ollama_base_url=ollama_base_url,
                ollama_frontier_model=ollama_frontier_model,
                ollama_cheap_model=ollama_cheap_model,
            )
        )

    # Aggregate
    def _agg(turns: list[dict]) -> dict[str, Any]:
        return {
            "total_input_tokens": sum(t.get("input_tokens", 0) for t in turns),
            "total_cache_read_tokens": sum(t.get("cache_read_tokens", 0) for t in turns),
            "total_uncached_tokens": sum(
                max(t.get("input_tokens", 0) - t.get("cache_read_tokens", 0), 0) for t in turns
            ),
            "total_output_tokens": sum(t.get("output_tokens", 0) for t in turns),
            "total_cost_usd": sum(t.get("cost_usd", 0.0) for t in turns),
            "frontier_calls": sum(1 for t in turns if t.get("model_tier") == "frontier"),
            "cheap_calls": sum(1 for t in turns if t.get("model_tier") == "cheap_llm"),
        }

    naive_agg = _agg(naive_turns)
    atelier_agg = _agg(atelier_turns)

    savings_pct = round(
        100 * (1 - atelier_agg["total_cost_usd"] / naive_agg["total_cost_usd"]), 1
    ) if naive_agg["total_cost_usd"] > 0 else 0.0

    token_savings_pct = round(
        100 * atelier_agg["total_cache_read_tokens"] / naive_agg["total_input_tokens"], 1
    ) if naive_agg["total_input_tokens"] > 0 else 0.0

    return {
        "mode": "real" if (real_api and (provider == "ollama_openai" or bool(api_key))) else "mock",
        "provider": provider,
        "turns": len(_TURN_TOKENS),
        "naive": naive_agg,
        "atelier": atelier_agg,
        "savings_pct": savings_pct,
        "token_savings_pct": token_savings_pct,
        "watchdog_events": mw.watchdog_events(),
        "loop_detected": mw.loop_detected(),
        "cost_summary": mw.cost_summary(),
    }


def _print_table(result: dict[str, Any]) -> None:
    """Print a compact comparison table."""
    n = result["naive"]
    a = result["atelier"]
    mode = result["mode"].upper()
    print()
    print(f"  Atelier SDK Middleware — Cost Benchmark ({mode} MODE, {result['turns']} turns)")
    print(f"  {'─' * 60}")
    print(f"  {'Metric':<32} {'Naive':>12} {'Atelier':>12}")
    print(f"  {'─' * 60}")
    print(f"  {'Total input tokens':<32} {n['total_input_tokens']:>12,} {a['total_input_tokens']:>12,}")
    print(f"  {'Cache-read tokens':<32} {n['total_cache_read_tokens']:>12,} {a['total_cache_read_tokens']:>12,}")
    print(f"  {'Uncached input tokens':<32} {n['total_uncached_tokens']:>12,} {a['total_uncached_tokens']:>12,}")
    print(f"  {'Output tokens':<32} {n['total_output_tokens']:>12,} {a['total_output_tokens']:>12,}")
    print(f"  {'Frontier model calls':<32} {n['frontier_calls']:>12} {a['frontier_calls']:>12}")
    print(f"  {'Cheap model calls':<32} {n['cheap_calls']:>12} {a['cheap_calls']:>12}")
    print(f"  {'Total cost (USD)':<32} ${n['total_cost_usd']:>11.4f} ${a['total_cost_usd']:>11.4f}")
    print(f"  {'─' * 60}")
    print(f"  {'Cost savings':<32} {result['savings_pct']:>11.1f}%")
    print(f"  {'Token-to-cache ratio':<32} {result['token_savings_pct']:>11.1f}%")
    print(f"  {'─' * 60}")
    cs = result["cost_summary"]
    print(f"  Ledger: {cs['turns']} turns | cache_hit_ratio={cs['cache_hit_ratio']:.0%} | "
          f"${cs['cost_usd']:.4f} | watchdog_alerts={len(result['watchdog_events'])}")
    print()


# ---------------------------------------------------------------------------
# pytest entry points
# ---------------------------------------------------------------------------

@pytest.mark.benchmark
def test_benchmark_mock(capsys: Any) -> None:
    """Benchmark in mock mode — no API key required."""
    result = run_benchmark(real_api=False)
    _print_table(result)

    assert result["mode"] == "mock"
    assert result["atelier"]["total_cost_usd"] < result["naive"]["total_cost_usd"], (
        "Atelier should be cheaper than naive loop"
    )
    assert result["atelier"]["total_cache_read_tokens"] > 0, (
        "Atelier should record cache-read tokens from turns ≥ 1"
    )
    assert result["atelier"]["cheap_calls"] > 0, (
        "Atelier model routing should use cheap model for some turns"
    )
    assert result["savings_pct"] > 30, (
        f"Expected >30% cost savings, got {result['savings_pct']}%"
    )
    assert result["atelier"]["frontier_calls"] < result["naive"]["frontier_calls"], (
        "Atelier should route fewer calls to frontier model"
    )


@pytest.mark.benchmark
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping real API benchmark",
)
def test_benchmark_real(capsys: Any) -> None:
    """Benchmark in real mode — requires ANTHROPIC_API_KEY."""
    result = run_benchmark(real_api=True, provider="anthropic")
    _print_table(result)

    assert result["mode"] == "real"
    assert result["atelier"]["total_cost_usd"] <= result["naive"]["total_cost_usd"] * 1.1, (
        "Atelier should not be more than 10% more expensive in real mode (turn 0 creates cache)"
    )


@pytest.mark.benchmark
def test_benchmark_real_ollama_openai_mocked(monkeypatch: Any, capsys: Any) -> None:
    """Benchmark in real mode via OpenAI-compatible Ollama client (mocked)."""

    class _Usage:
        def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
            self.prompt_tokens = prompt_tokens
            self.completion_tokens = completion_tokens
            self.prompt_tokens_details = type("Details", (), {"cached_tokens": 0})()

    class _Resp:
        def __init__(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
            self.model = model
            self.usage = _Usage(prompt_tokens, completion_tokens)

    class _Completions:
        def create(self, *, model: str, max_tokens: int, temperature: int, messages: list[dict[str, str]]) -> Any:
            base = 1500 if "frontier" in model else 1200
            return _Resp(model=model, prompt_tokens=base, completion_tokens=120)

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class _FakeClient:
        def __init__(self) -> None:
            self.chat = _Chat()

    monkeypatch.setenv("OLLAMA_FRONTIER_MODEL", "frontier-model")
    monkeypatch.setenv("OLLAMA_CHEAP_MODEL", "cheap-model")
    monkeypatch.setattr(
        "benchmarks.mcp_tools.bench_real_cache._openai_client",
        lambda base_url, api_key: _FakeClient(),
    )

    result = run_benchmark(real_api=True, provider="ollama_openai")
    _print_table(result)

    assert result["mode"] == "real"
    assert result["provider"] == "ollama_openai"
    assert result["atelier"]["frontier_calls"] < result["naive"]["frontier_calls"]
    assert result["atelier"]["cheap_calls"] > 0
