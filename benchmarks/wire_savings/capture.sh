#!/usr/bin/env bash
# Start a mitmproxy capture for ONE Claude Code run.
#
#   ./capture.sh atelier_off.flow      # run a task with Atelier disabled
#   ./capture.sh atelier_on.flow       # run the SAME task with Atelier enabled
#
# Then diff them:
#   uv run python -m benchmarks.wire_savings.report \
#       atelier_off=atelier_off.flow atelier_on=atelier_on.flow
set -euo pipefail

OUT="${1:?usage: capture.sh OUTPUT.flow}"
CA="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"
PORT="${MITM_PORT:-8080}"

if ! command -v mitmdump >/dev/null 2>&1; then
  echo "mitmdump not found. Install with: uv pip install mitmproxy" >&2
  exit 1
fi

cat <<EOF
In ANOTHER terminal, route Claude Code through this proxy, then do ONE task:

  export HTTPS_PROXY=http://127.0.0.1:${PORT}
  export HTTP_PROXY=http://127.0.0.1:${PORT}
  export NODE_EXTRA_CA_CERTS=${CA}   # without this, Claude fails *silently*
  # --- Amazon Bedrock auth (no Anthropic API key needed) ---
  export CLAUDE_CODE_USE_BEDROCK=1
  export AWS_REGION=us-east-1
  export AWS_CA_BUNDLE=${CA}
  export AWS_BEARER_TOKEN_BEDROCK=...   # or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
  claude

Capturing to '${OUT}'. Press q (or Ctrl-C) in mitmproxy when the task is done.
EOF

exec mitmdump --listen-port "${PORT}" -w "${OUT}"
