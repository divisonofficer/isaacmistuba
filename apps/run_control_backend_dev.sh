#!/usr/bin/env bash
set -euo pipefail

ROBOMITUBA_ROOT="${ROBOMITUBA_ROOT:-/jarvis/project/robomituba}"
BACKEND_HOST="${BACKEND_HOST:-${RENDER_DAEMON_HOST:-127.0.0.1}}"
BACKEND_PORT="${BACKEND_PORT:-${RENDER_DAEMON_PORT:-8765}}"
LOCAL_DEV_ROOT="${LOCAL_DEV_ROOT:-/tmp/robomituba_control_backend_dev}"

if [[ ! -d "$ROBOMITUBA_ROOT" ]]; then
  echo "[backend] robomituba root not found: $ROBOMITUBA_ROOT" >&2
  exit 1
fi

mkdir -p "$LOCAL_DEV_ROOT"

USER_SITE=""
if [[ -n "${SUDO_USER:-}" ]]; then
  USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
  if [[ -n "$USER_HOME" ]]; then
    USER_SITE="$USER_HOME/.local/lib/python3.10/site-packages"
  fi
fi

export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export PYTHONFAULTHANDLER="${PYTHONFAULTHANDLER:-1}"
export ROBOMITUBA_RENDER_INPROCESS="${ROBOMITUBA_RENDER_INPROCESS:-0}"
export ROBOMITUBA_BACKEND_ONLY="${ROBOMITUBA_BACKEND_ONLY:-1}"
export ROBOMITUBA_RENDER_QUEUE_URL="${ROBOMITUBA_RENDER_QUEUE_URL:-http://127.0.0.1:8766}"
export ROBOMITUBA_DAEMON_DEBUG_LOG="${ROBOMITUBA_DAEMON_DEBUG_LOG:-1}"
export PYTHONPATH="$ROBOMITUBA_ROOT/modules/mitsuba_converter/src:$ROBOMITUBA_ROOT/modules/robomituba_bridge/src:$ROBOMITUBA_ROOT/modules/navigation_dataset/src${USER_SITE:+:$USER_SITE}:${PYTHONPATH:-}"
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"
export ROBOMITUBA_TEMP_ROOT="$LOCAL_DEV_ROOT"

cd "$ROBOMITUBA_ROOT"
echo "[backend] robomituba root: $ROBOMITUBA_ROOT"
echo "[backend] backend-only: $ROBOMITUBA_BACKEND_ONLY"
echo "[backend] url: http://$BACKEND_HOST:$BACKEND_PORT"
echo "[backend] render queue proxy: $ROBOMITUBA_RENDER_QUEUE_URL"
echo "[backend] render queue workers disabled in this process; start scripts/run_render_queue_optix7.sh separately for GPU jobs."
exec python3 -u "$ROBOMITUBA_ROOT/apps/run_render_daemon.py" --repo-root "$ROBOMITUBA_ROOT" --host "$BACKEND_HOST" --port "$BACKEND_PORT"
