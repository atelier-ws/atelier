"""Vendor price tables and CandidateModel definitions.

See docs/plans/active/commercial-wedge/W2-counterfactual.md for the full spec.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    """Per-million-token prices for a model."""

    input: float  # USD per million input tokens
    output: float  # USD per million output tokens

    def cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input + output_tokens * self.output) / 1_000_000


@dataclass(frozen=True)
class CandidateModel:
    """A vendor+model pair with pricing and capability metadata."""

    vendor: str
    model_id: str
    tier: str  # "cheap" | "high"
    pricing: ModelPricing
    supports_tool_use: bool = True
    output_multiplier: float = 1.0
    context_window: int = 200_000


@dataclass(frozen=True)
class PricingTable:
    """Versioned collection of CandidateModel entries."""

    version: str
    candidates: tuple[CandidateModel, ...]

    def candidates_for_vendor(self, vendor: str) -> tuple[CandidateModel, ...]:
        return tuple(c for c in self.candidates if c.vendor == vendor)


# ---------------------------------------------------------------------------
# Bundled default pricing table (version-stamped)
# ---------------------------------------------------------------------------

_DEFAULT_CANDIDATES: tuple[CandidateModel, ...] = (
    # Anthropic
    CandidateModel(
        vendor="anthropic",
        model_id="claude-haiku-4-5",
        tier="cheap",
        pricing=ModelPricing(input=0.80, output=4.00),
        supports_tool_use=True,
    ),
    CandidateModel(
        vendor="anthropic",
        model_id="claude-sonnet-4-5",
        tier="high",
        pricing=ModelPricing(input=3.00, output=15.00),
        supports_tool_use=True,
    ),
    CandidateModel(
        vendor="anthropic",
        model_id="claude-opus-4-5",
        tier="high",
        pricing=ModelPricing(input=15.00, output=75.00),
        supports_tool_use=True,
        output_multiplier=1.5,
    ),
    CandidateModel(
        vendor="anthropic",
        model_id="claude-fable-5",
        tier="high",
        pricing=ModelPricing(input=10.00, output=50.00),
        supports_tool_use=True,
        context_window=1_000_000,
    ),
    # OpenAI
    CandidateModel(
        vendor="openai",
        model_id="gpt-4o-mini",
        tier="cheap",
        pricing=ModelPricing(input=0.15, output=0.60),
        supports_tool_use=True,
    ),
    CandidateModel(
        vendor="openai",
        model_id="gpt-4o",
        tier="high",
        pricing=ModelPricing(input=2.50, output=10.00),
        supports_tool_use=True,
    ),
    # Google
    CandidateModel(
        vendor="google",
        model_id="gemini-2.0-flash",
        tier="cheap",
        pricing=ModelPricing(input=0.10, output=0.40),
        supports_tool_use=True,
    ),
    CandidateModel(
        vendor="google",
        model_id="gemini-2.0-pro",
        tier="high",
        pricing=ModelPricing(input=1.25, output=5.00),
        supports_tool_use=True,
    ),
    # AWS Bedrock (Claude models via Bedrock — same pricing as direct but through AWS)
    CandidateModel(
        vendor="bedrock",
        model_id="bedrock/anthropic.claude-haiku-4-5-v1:0",
        tier="cheap",
        pricing=ModelPricing(input=0.80, output=4.00),
        supports_tool_use=True,
    ),
    CandidateModel(
        vendor="bedrock",
        model_id="bedrock/anthropic.claude-sonnet-4-5-v1:0",
        tier="high",
        pricing=ModelPricing(input=3.00, output=15.00),
        supports_tool_use=True,
    ),
    # GCP Vertex AI (Claude and Gemini on Vertex)
    CandidateModel(
        vendor="vertex",
        model_id="vertex_ai/gemini-2.0-flash",
        tier="cheap",
        pricing=ModelPricing(input=0.075, output=0.30),
        supports_tool_use=True,
    ),
    CandidateModel(
        vendor="vertex",
        model_id="vertex_ai/claude-3-5-sonnet@20241022",
        tier="high",
        pricing=ModelPricing(input=3.00, output=15.00),
        supports_tool_use=True,
    ),
    # Azure OpenAI
    CandidateModel(
        vendor="azure",
        model_id="azure/gpt-4o-mini",
        tier="cheap",
        pricing=ModelPricing(input=0.15, output=0.60),
        supports_tool_use=True,
    ),
    CandidateModel(
        vendor="azure",
        model_id="azure/gpt-4o",
        tier="high",
        pricing=ModelPricing(input=2.50, output=10.00),
        supports_tool_use=True,
    ),
    # OpenRouter — access to multiple providers with one key
    CandidateModel(
        vendor="openrouter",
        model_id="openrouter/anthropic/claude-haiku-4-5",
        tier="cheap",
        pricing=ModelPricing(input=0.90, output=4.50),  # slight markup over direct
        supports_tool_use=True,
    ),
    CandidateModel(
        vendor="openrouter",
        model_id="openrouter/anthropic/claude-sonnet-4-5",
        tier="high",
        pricing=ModelPricing(input=3.30, output=16.50),
        supports_tool_use=True,
    ),
    # Groq (ultra-fast inference, very cheap)
    CandidateModel(
        vendor="groq",
        model_id="groq/llama-3.3-70b-versatile",
        tier="cheap",
        pricing=ModelPricing(input=0.59, output=0.79),
        supports_tool_use=True,
    ),
    CandidateModel(
        vendor="groq",
        model_id="groq/llama-3.1-8b-instant",
        tier="cheap",
        pricing=ModelPricing(input=0.05, output=0.08),
        supports_tool_use=False,
    ),
    # Mistral
    CandidateModel(
        vendor="mistral",
        model_id="mistral/mistral-large-latest",
        tier="high",
        pricing=ModelPricing(input=2.00, output=6.00),
        supports_tool_use=True,
    ),
    CandidateModel(
        vendor="mistral",
        model_id="mistral/mistral-small-latest",
        tier="cheap",
        pricing=ModelPricing(input=0.20, output=0.60),
        supports_tool_use=True,
    ),
    # Ollama (local — pricing is $0 but has GPU cost; use near-zero for routing logic)
    CandidateModel(
        vendor="ollama",
        model_id="ollama/llama3.2",
        tier="cheap",
        pricing=ModelPricing(input=0.001, output=0.001),
        supports_tool_use=False,
    ),
    CandidateModel(
        vendor="ollama",
        model_id="ollama/qwen2.5-coder:7b",
        tier="cheap",
        pricing=ModelPricing(input=0.001, output=0.001),
        supports_tool_use=False,
    ),
    # Together AI
    CandidateModel(
        vendor="together",
        model_id="together_ai/meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        tier="cheap",
        pricing=ModelPricing(input=0.88, output=0.88),
        supports_tool_use=True,
    ),
    # Fireworks AI
    CandidateModel(
        vendor="fireworks",
        model_id="fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct",
        tier="cheap",
        pricing=ModelPricing(input=0.90, output=0.90),
        supports_tool_use=True,
    ),
)

_DEFAULT_TABLE = PricingTable(version="2026-06-10", candidates=_DEFAULT_CANDIDATES)


def load_pricing_table(_version: str | None = None) -> PricingTable:
    """Load the bundled pricing table (version pin is a no-op until W2 is fully implemented)."""
    return _DEFAULT_TABLE


__all__ = ["CandidateModel", "ModelPricing", "PricingTable", "load_pricing_table"]
