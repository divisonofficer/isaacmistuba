#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOMITUBA_ROOT="$(cd "$APP_DIR/../.." && pwd)"
BACKEND_PORT="${IR_VIEWER_BACKEND_PORT:-8780}"
export ROBOMITUBA_IR_GPU_INDICES="${ROBOMITUBA_IR_GPU_INDICES:-0,1,2,3}"

cd "$ROBOMITUBA_ROOT"
python3 -u "$APP_DIR/server.py" --host 0.0.0.0 --port "$BACKEND_PORT" &
BACKEND_PID=$!
cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$APP_DIR"
IR_VIEWER_BACKEND="http://127.0.0.1:$BACKEND_PORT" npm run dev
