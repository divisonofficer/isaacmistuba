#!/usr/bin/env bash
set -euo pipefail

# Launch the control-plane daemon in subprocess render mode with an OptiX 7
# Mitsuba worker. This keeps the daemon Python lightweight while the worker
# uses a Python 3.10 env that can import the older Mitsuba wheel.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Compiled Mitsuba/Dr.Jit artifacts are host-specific and must not live below
# the NAS-backed repository. Override this per host when needed.

# Pick the Mitsuba build that matches the host GPU's compute capability.
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
: "${ROBOMITUBA_RENDER_GPU_INDICES:=0,1,2,3}"
: "${ROBOMITUBA_RENDER_WORKER_BACKLOG_PER_GPU:=2}"
: "${ROBOMITUBA_FULL_RENDER_DISABLE_CUDA:=0}"
: "${ROBOMITUBA_DISABLE_CPU_FALLBACK:=1}"
: "${ROBOMITUBA_CPU_SPP_CAP:=0}"
: "${ROBOMITUBA_TEXTURE_MAX_RESOLUTION:=1024}"
: "${ROBOMITUBA_WORKER_HEARTBEAT_TIMEOUT_S:=600}"
: "${ROBOMITUBA_SCENE_LOAD_CONCURRENCY:=1}"
: "${ROBOMITUBA_RENDER_INPROCESS:=0}"
: "${PYTHONUNBUFFERED:=1}"

export ROBOMITUBA_MITSUBA_PYTHON
export ROBOMITUBA_MITSUBA_BUILD_DIR
export ROBOMITUBA_MITSUBA_PYTHONPATH
export ROBOMITUBA_RENDER_GPU_INDICES
export ROBOMITUBA_RENDER_WORKER_BACKLOG_PER_GPU
export ROBOMITUBA_FULL_RENDER_DISABLE_CUDA
export ROBOMITUBA_DISABLE_CPU_FALLBACK
export ROBOMITUBA_CPU_SPP_CAP
export ROBOMITUBA_TEXTURE_MAX_RESOLUTION
export ROBOMITUBA_WORKER_HEARTBEAT_TIMEOUT_S
export ROBOMITUBA_SCENE_LOAD_CONCURRENCY
export ROBOMITUBA_RENDER_INPROCESS
export PYTHONUNBUFFERED

echo "[launcher] Mitsuba build: $ROBOMITUBA_MITSUBA_BUILD_DIR"

exec python -u "$REPO_ROOT/apps/run_render_daemon.py" "$@"
