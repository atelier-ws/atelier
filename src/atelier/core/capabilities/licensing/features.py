"""Registry of the paid ("Pro") capability surface.

Every gated feature has a stable key and a human description. The open-source
core *contains* these capabilities; the license check only decides whether the
paid control surfaces (e.g. ``atelier optimize apply``) are unlocked. Adding a
new gate is a one-line entry here plus an ``entitlements.require()`` call at the
seam that activates the capability.
"""

from __future__ import annotations

# Stable key -> short human description (shown in `atelier license status` and
# in upgrade prompts). Keys are the contract; descriptions can change freely.
PRO_FEATURES: dict[str, str] = {
    "optimizer": "Apply the optimization policy that activates the savings engine",
    "context_compression": "Context compression and deduplication on the live turn",
    "prefix_cache": "Prefix-cache planning for warmer provider caches",
    "scoped_context": "Scoped-context pruning and line-level skimming",
    "budget_optimizer": "Per-session budget optimization",
    "model_routing": "Automatic routing to cheaper models per turn",
    "cross_vendor_routing": "Cross-vendor routing across providers",
    "savings_dashboard": "Full savings breakdown, history, and optimization detail",
    "unlimited_repos": "Optimize more than one repository",
}


def is_pro_feature(feature: str) -> bool:
    return feature in PRO_FEATURES


def describe(feature: str) -> str:
    return PRO_FEATURES.get(feature, feature)
