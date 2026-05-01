"""Operating laws — environment specifications for different domains."""

from __future__ import annotations

# Re-export from foundation where the logic lives
from atelier.core.foundation.environments import (
    load_environment_file,
    load_environments_from_dir,
    load_packaged_environments,
    match_environments,
)

__all__ = [
    "load_environment_file",
    "load_environments_from_dir",
    "load_packaged_environments",
    "match_environments",
]
