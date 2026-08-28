#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOMITUBA_ROOT="$(cd "$APP_DIR/../.." && pwd)"
BACKEND_PORT="${IR_VIEWER_BACKEND_PORT:-8780}"
export ROBOMITUBA_IR_GPU_INDICES="${ROBOMITUBA_IR_GPU_INDICES:-0,1,2,3,4,5,6,7}"
# Three CPU-heavy Infinigen generators fit the deployed 64-core / high-memory
# host and keep the 24-hour scene budget from waiting behind one slow room.
export ROBOMITUBA_INFINIGEN_CONCURRENCY="${ROBOMITUBA_INFINIGEN_CONCURRENCY:-3}"
# Bound one pathological annealing run so the queue can move to its isolated
# lower-clutter variation instead of consuming most of the daily budget.
export ROBOMITUBA_INFINIGEN_GENERATE_TIMEOUT_S="${ROBOMITUBA_INFINIGEN_GENERATE_TIMEOUT_S:-2700}"
# A 3090 has ample headroom for one persistent Blender worker per GPU in the
# IR queue.  Keep the override for constrained hosts, but use the full pool
# by default so a render parent does not leave half the cluster idle.
export ROBOMITUBA_MAX_GPUS_PER_RENDER_PARENT="${ROBOMITUBA_MAX_GPUS_PER_RENDER_PARENT:-8}"

cd "$ROBOMITUBA_ROOT"
python3 -u "$APP_DIR/server.py" --host 0.0.0.0 --port "$BACKEND_PORT" &
BACKEND_PID=$!
cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$APP_DIR"
IR_VIEWER_BACKEND="http://127.0.0.1:$BACKEND_PORT" npm run dev
