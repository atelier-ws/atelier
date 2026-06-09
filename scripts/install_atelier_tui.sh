#!/usr/bin/env bash
# install_atelier_tui.sh — Install atelier-tui host integration.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../integrations/atelier-tui/install.sh" "$@"
