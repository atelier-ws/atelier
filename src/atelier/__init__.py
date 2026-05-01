"""Atelier — Beseam Reasoning Runtime.

A reasoning/procedure runtime for coding and product agents. Combines:

1. ReasonBlocks-style reasoning reuse (retrieve known procedures before/during runs).
2. Lemma-style failure improvement (record traces, detect recurring failures).
3. Rubric-style verification (check plans/outputs against expert rubrics).

This is NOT memory. It stores observable traces, explicit procedures,
failures, validation results, and reusable lessons — never hidden chain-of-thought
or user preferences.
"""

from atelier.core import service
from atelier.core.foundation.models import (
    FailureCluster,
    PlanCheckResult,
    ReasonBlock,
    RescueResult,
    Rubric,
    RubricResult,
    Trace,
)
from atelier.gateway import hosts, integrations, sdk
from atelier.gateway.sdk import AtelierClient, LocalClient, MCPClient, RemoteClient
from atelier.infra import storage

__version__ = "0.1.0"

__all__ = [
    "AtelierClient",
    "FailureCluster",
    "LocalClient",
    "MCPClient",
    "PlanCheckResult",
    "ReasonBlock",
    "RemoteClient",
    "RescueResult",
    "Rubric",
    "RubricResult",
    "Trace",
    "__version__",
    "hosts",
    "integrations",
    "sdk",
    "service",
    "storage",
]
