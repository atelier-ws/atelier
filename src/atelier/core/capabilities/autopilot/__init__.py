"""Autopilot choreography (M5).

A thin, opt-out layer that auto-fires Atelier's *own* context capabilities at
host lifecycle events (session start, user prompt, post-edit). It never drives
the model or manages phases — it only sequences capabilities in response to
events the host emits, and returns an action the host (hook) delivers. This is
choreography, not orchestration.
"""

from __future__ import annotations

from .capability import AutopilotCapability
from .models import AutopilotAction, AutopilotConfig, AutopilotEvent

__all__ = ["AutopilotAction", "AutopilotCapability", "AutopilotConfig", "AutopilotEvent"]
