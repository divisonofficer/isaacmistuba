#!/usr/bin/env bash
set -euo pipefail

# Launch the GPU render queue daemon with OptiX 7 Mitsuba workers.
# Default port is 8766 so it can run next to apps/run_control_backend_dev.sh
# on 8765. Set RENDER_QUEUE_PORT=8765 when using it as the all-in-one daemon.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Keep compiled Mitsuba/Dr.Jit artifacts on host-local storage, never in the
# NAS checkout. Override ROBOMITUBA_MITSUBA_BUILD_DIR for a custom disk.

: "${RENDER_QUEUE_AUTO_GPUS:=0}"
: "${RENDER_QUEUE_AUTO_GPU_MEMORY_USED_PCT_MAX:=10}"
: "${RENDER_QUEUE_HOST:=127.0.0.1}"
: "${RENDER_QUEUE_PORT:=8766}"
# Pick Mitsuba build by host GPU compute capability.
#  - sm_120 (RTX 50 / Blackwell) → device B build  (modules/mitsuba3, OptiX 8)
#  - everything else             → device A build  (modules/mitsuba3-optix7, OptiX 7)
# Override either default by exporting the env var before running this launcher.
_compute_cap="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d '[:space:]' || true)"

if [[ -z "${ROBOMITUBA_MITSUBA_BUILD_DIR:-}" ]]; then
  if [[ "$_compute_cap" == "12.0" ]]; then
    ROBOMITUBA_MITSUBA_BUILD_DIR="${ROBOMITUBA_DEVICE1_MITSUBA_BUILD_DIR:-${HOME:-/tmp}/robomituba-build/mitsuba3}"
  else
    ROBOMITUBA_MITSUBA_BUILD_DIR="${ROBOMITUBA_DEVICE2_MITSUBA_BUILD_DIR:-${HOME:-/tmp}/robomituba-build/mitsuba3-optix7}"
  fi
fi
case "$ROBOMITUBA_MITSUBA_BUILD_DIR" in
  /jarvis/*)
    echo "[launcher] ERROR: compiled Mitsuba build must be host-local, got $ROBOMITUBA_MITSUBA_BUILD_DIR" >&2
    exit 2
    ;;
esac
if [[ "$_compute_cap" == "12.0" ]]; then
  : "${ROBOMITUBA_MITSUBA_PYTHON:=/usr/bin/python3}"
  : "${ROBOMITUBA_MITSUBA_PYTHONPATH:=${ROBOMITUBA_MITSUBA_BUILD_DIR}/python}"
else
  : "${ROBOMITUBA_MITSUBA_PYTHON:=/root/miniconda3/envs/mitsuba_optix7/bin/python}"
  : "${ROBOMITUBA_MITSUBA_PYTHONPATH:=${ROBOMITUBA_MITSUBA_BUILD_DIR}/python}"
fi
: "${ROBOMITUBA_RENDER_GPU_INDICES:=1,2,3,4}"
: "${ROBOMITUBA_RENDER_WORKER_BACKLOG_PER_GPU:=2}"
: "${ROBOMITUBA_RENDER_WORKER_COUNT:=4}"
: "${ROBOMITUBA_FULL_RENDER_DISABLE_CUDA:=0}"
: "${ROBOMITUBA_DISABLE_CPU_FALLBACK:=1}"
: "${ROBOMITUBA_CPU_SPP_CAP:=0}"
: "${ROBOMITUBA_TEXTURE_MAX_RESOLUTION:=1024}"
: "${ROBOMITUBA_WORKER_HEARTBEAT_TIMEOUT_S:=600}"
: "${ROBOMITUBA_SCENE_LOAD_CONCURRENCY:=1}"
: "${ROBOMITUBA_RENDER_INPROCESS:=0}"
: "${ROBOMITUBA_BACKEND_ONLY:=0}"
: "${PYTHONUNBUFFERED:=1}"

EXPLICIT_GPUS=""
EXPLICIT_GPUS_SET=0

discover_idle_gpus() {
  local threshold="$1"

  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "[render-queue] ERROR: --auto-gpus requires nvidia-smi in PATH" >&2
    return 1
  fi

  nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits \
    | awk -F, -v threshold="$threshold" '
        function trim(value) {
          gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
          return value
        }
        {
          gpu_index = trim($1)
          used = trim($2) + 0
          total = trim($3) + 0
          if (total <= 0) {
            next
          }
          memory_used_pct = used * 100 / total
          if (memory_used_pct < threshold) {
            if (out != "") {
              out = out ","
            }
            out = out gpu_index
          }
        }
        END {
          print out
        }'
}

DAEMON_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpus)
      if [[ $# -lt 2 ]]; then
        echo "[render-queue] ERROR: --gpus requires comma-separated GPU indices (for example: --gpus 1,2,3)" >&2
        exit 2
      fi
      EXPLICIT_GPUS="$2"
      EXPLICIT_GPUS_SET=1
      shift 2
      ;;
    --gpus=*)
      EXPLICIT_GPUS="${1#*=}"
      EXPLICIT_GPUS_SET=1
      shift
      ;;
    --auto-gpus)
      RENDER_QUEUE_AUTO_GPUS=1
      shift
      ;;
    --gpu-memory-used-pct-max)
      if [[ $# -lt 2 ]]; then
        echo "[render-queue] ERROR: --gpu-memory-used-pct-max requires a numeric value" >&2
        exit 2
      fi
      RENDER_QUEUE_AUTO_GPU_MEMORY_USED_PCT_MAX="$2"
      shift 2
      ;;
    --gpu-memory-used-pct-max=*)
      RENDER_QUEUE_AUTO_GPU_MEMORY_USED_PCT_MAX="${1#*=}"
      shift
      ;;
    --)
      shift
      DAEMON_ARGS+=("$@")
      break
      ;;
    *)
      DAEMON_ARGS+=("$1")
      shift
      ;;
  esac
done
set -- "${DAEMON_ARGS[@]}"

if [[ "$EXPLICIT_GPUS_SET" == "1" ]]; then
  if [[ "$RENDER_QUEUE_AUTO_GPUS" == "1" ]]; then
    echo "[render-queue] ERROR: --gpus and --auto-gpus cannot be used together" >&2
    exit 2
  fi
  if ! [[ "$EXPLICIT_GPUS" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
    echo "[render-queue] ERROR: --gpus must be comma-separated GPU indices (for example: --gpus 1,2,3)" >&2
    exit 2
  fi
  ROBOMITUBA_RENDER_GPU_INDICES="$EXPLICIT_GPUS"
  ROBOMITUBA_RENDER_WORKER_COUNT="$(awk -F, '{ print NF }' <<<"$ROBOMITUBA_RENDER_GPU_INDICES")"
fi

if [[ "$RENDER_QUEUE_AUTO_GPUS" == "1" ]]; then
  if ! [[ "$RENDER_QUEUE_AUTO_GPU_MEMORY_USED_PCT_MAX" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "[render-queue] ERROR: RENDER_QUEUE_AUTO_GPU_MEMORY_USED_PCT_MAX must be numeric" >&2
    exit 2
  fi

  ROBOMITUBA_RENDER_GPU_INDICES="$(discover_idle_gpus "$RENDER_QUEUE_AUTO_GPU_MEMORY_USED_PCT_MAX")"
  if [[ -z "$ROBOMITUBA_RENDER_GPU_INDICES" ]]; then
    echo "[render-queue] ERROR: no GPUs found below ${RENDER_QUEUE_AUTO_GPU_MEMORY_USED_PCT_MAX}% memory use" >&2
    exit 1
  fi
  ROBOMITUBA_RENDER_WORKER_COUNT="$(awk -F, '{ print NF }' <<<"$ROBOMITUBA_RENDER_GPU_INDICES")"
fi

export ROBOMITUBA_MITSUBA_PYTHON
export ROBOMITUBA_MITSUBA_BUILD_DIR
export ROBOMITUBA_MITSUBA_PYTHONPATH
export ROBOMITUBA_RENDER_GPU_INDICES
export ROBOMITUBA_RENDER_WORKER_BACKLOG_PER_GPU
export ROBOMITUBA_RENDER_WORKER_COUNT
export ROBOMITUBA_FULL_RENDER_DISABLE_CUDA
export ROBOMITUBA_DISABLE_CPU_FALLBACK
export ROBOMITUBA_CPU_SPP_CAP
export ROBOMITUBA_TEXTURE_MAX_RESOLUTION
export ROBOMITUBA_WORKER_HEARTBEAT_TIMEOUT_S
export ROBOMITUBA_SCENE_LOAD_CONCURRENCY
export ROBOMITUBA_RENDER_INPROCESS
export ROBOMITUBA_BACKEND_ONLY
export PYTHONUNBUFFERED
export PYTHONPATH="$REPO_ROOT/modules/mitsuba_converter/src:$REPO_ROOT/modules/robomituba_bridge/src:$REPO_ROOT/modules/navigation_dataset/src:${PYTHONPATH:-}"

echo "[render-queue] Mitsuba build: $ROBOMITUBA_MITSUBA_BUILD_DIR"
echo "[render-queue] url: http://$RENDER_QUEUE_HOST:$RENDER_QUEUE_PORT"
if [[ "$RENDER_QUEUE_AUTO_GPUS" == "1" ]]; then
  echo "[render-queue] auto GPUs: memory_used_pct<${RENDER_QUEUE_AUTO_GPU_MEMORY_USED_PCT_MAX}%"
fi
echo "[render-queue] GPUs: $ROBOMITUBA_RENDER_GPU_INDICES workers=$ROBOMITUBA_RENDER_WORKER_COUNT backlog_per_gpu=$ROBOMITUBA_RENDER_WORKER_BACKLOG_PER_GPU scene_load_concurrency=$ROBOMITUBA_SCENE_LOAD_CONCURRENCY"
echo "[render-queue] texture max: $ROBOMITUBA_TEXTURE_MAX_RESOLUTION GPU-only cpu_fallback_disabled=$ROBOMITUBA_DISABLE_CPU_FALLBACK"

exec python3 -u "$REPO_ROOT/apps/run_render_daemon.py" --repo-root "$REPO_ROOT" --host "$RENDER_QUEUE_HOST" --port "$RENDER_QUEUE_PORT" "$@"
