# Optional Integrations (Legacy)

The `integrations/` module provides opt-in third-party integrations. Most host-specific logic has been moved to `atelier.hosts.host_adapters`.

## Structure

### Still in this module:
- `openmemory.py` — OpenMemory interoperability wrapper (no duplicate exists elsewhere)
- `ledger_reconstructor.py` — Ledger reconstruction utilities
- `_session_parser.py` — Shared session parsing logic (duplicate: also in hosts/host_adapters/)

### Moved to other modules:
- ✗ `claude.py` → `atelier.hosts.host_adapters.claude`
- ✗ `codex.py` → `atelier.hosts.host_adapters.codex`
- ✗ `copilot.py` → `atelier.hosts.host_adapters.copilot`
- ✗ `opencode.py` → `atelier.hosts.host_adapters.opencode`
- ✗ `memory/` → `atelier.memory_bridges`

## Backward Compatibility

The following imports are maintained for compatibility:
```python
from atelier.integrations.memory import GenericVectorMemoryAdapter  # Routes to memory_bridges
```

## Deprecation Path

- `atelier.integrations.claude`, `.codex`, `.copilot`, `.opencode` — **Deprecated**, use `atelier.hosts.host_adapters`
- `atelier.integrations.memory.*` — **Deprecated**, use `atelier.memory_bridges`

## Related

- `atelier.hosts` — Unified host integration point (hosts/host_adapters/)
- `atelier.memory_bridges` — Memory interoperability adapters
