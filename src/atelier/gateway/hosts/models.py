"""Host registration and identification.

Each host gets a UUID (persistent) + fingerprint (validation).
UUID identifies the host. Fingerprint validates it's the same physical machine.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class HostFingerprint(BaseModel):
    """Fingerprint = hash(hostname + username + install_path)."""

    hostname: str
    username: str
    install_path: str
    fingerprint_hash: str

    @classmethod
    def generate(cls) -> HostFingerprint:
        """Generate fingerprint from current environment."""
        hostname = os.environ.get("HOSTNAME", "unknown")
        username = os.environ.get("USER", "unknown")
        install_path = str(Path(__file__).parent.parent.parent.parent)

        data = f"{hostname}:{username}:{install_path}".encode()
        fingerprint_hash = hashlib.sha256(data).hexdigest()[:16]

        return cls(
            hostname=hostname,
            username=username,
            install_path=install_path,
            fingerprint_hash=fingerprint_hash,
        )


class HostRegistration(BaseModel):
    """Registered host with UUID + fingerprint."""

    host_id: UUID = Field(default_factory=uuid4, description="Unique host identifier")
    fingerprint: HostFingerprint
    atelier_version: str
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(json_encoders={UUID: str, datetime: lambda v: v.isoformat()})


class HostStatus(BaseModel):
    """Current host status (packs, tools, version)."""

    host_id: UUID
    atelier_version: str
    installed_packs: list[dict[str, str]] = Field(
        default_factory=list, description="[{pack_id, version}, ...]"
    )
    available_mcp_tools: list[str] = Field(
        default_factory=list, description="List of MCP tool names"
    )
    active_domains: list[str] = Field(default_factory=list)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(json_encoders={UUID: str, datetime: lambda v: v.isoformat()})


class HostInfo(BaseModel):
    """Public host information."""

    host_id: str
    label: str
    description: str
    installed: bool
    installed_packs: list[dict[str, str]] = Field(default_factory=list)
    mcp_tools_count: int = 0
    atelier_version: str | None = None
    last_seen: str | None = None
    install_command: str | None = None


def generate_host_id() -> UUID:
    """Generate a new host UUID."""
    return uuid4()
