## Atelier CLI Module

**Purpose**: Command-line interface for pack management and runtime operations.

**Key files**:
- `pack.py`: Pack management commands (list, install, uninstall, validate, info, search, benchmark, publish)
- `__main__.py`: Main entry point with click integration
- `__init__.py`: Module initialization

**Entry points**:
- CLI: `python -m atelier.cli pack --help`
- Commands:
  - `pack list` - List installed packs
  - `pack search <query>` - Search installed + official internal packs
  - `pack install <path|url>` - Install pack with dry-run support
  - `pack uninstall <id>` - Remove pack
  - `pack validate <path>` - Validate pack structure
  - `pack info <id>` - Show pack metadata
  - `pack benchmark <id>` - Run pack benchmarks (deferred to Phase D.6)

**Design**:
- Core `PackCLI` class handles all operations
- Uses existing `PackManager` from `atelier.packs`
- Output formats: human-readable tables + JSON for scripting
- Click integration for command parsing (optional fallback to manual parsing)

**Dependencies**:
- `click` (optional, graceful fallback)
- `atelier.packs.PackManager`
- `atelier.packs.registry` (internal catalog)
- `atelier.packs.validator`
