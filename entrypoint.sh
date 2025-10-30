#!/usr/bin/env bash
set -euo pipefail
TOOLS_HOST="${TOOLS_HOST:-0.0.0.0}"; TOOLS_PORT="${TOOLS_PORT:-7001}";
GREEN_HOST="${GREEN_HOST:-0.0.0.0}"; GREEN_PORT="${GREEN_PORT:-7002}";
export TOOLS_BASE_URL="http://${TOOLS_HOST}:${TOOLS_PORT}"
python -m tools.server --host "$TOOLS_HOST" --port "$TOOLS_PORT" &
python -m green_agent.server --host "$GREEN_HOST" --port "$GREEN_PORT"
