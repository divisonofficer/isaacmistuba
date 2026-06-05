#!/usr/bin/env bash
set -euo pipefail

# Launch the control-plane daemon in subprocess render mode with an OptiX 7
# Mitsuba worker. This keeps the daemon Python lightweight while the worker
# uses a Python 3.10 env that can import the older Mitsuba wheel.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${ROBOMITUBA_MITSUBA_PYTHON:=/root/miniconda3/envs/mitsuba_optix7/bin/python}"
: "${ROBOMITUBA_MITSUBA_PYTHONPATH:=/jarvis/project/robomituba/build/mitsuba3-optix7/python}"
: "${ROBOMITUBA_RENDER_GPU_INDICES:=0,1,2,3}"
: "${ROBOMITUBA_FULL_RENDER_DISABLE_CUDA:=0}"
: "${ROBOMITUBA_DISABLE_CPU_FALLBACK:=1}"
: "${ROBOMITUBA_CPU_SPP_CAP:=0}"
: "${ROBOMITUBA_TEXTURE_MAX_RESOLUTION:=1024}"
: "${ROBOMITUBA_WORKER_HEARTBEAT_TIMEOUT_S:=600}"
: "${ROBOMITUBA_SCENE_LOAD_CONCURRENCY:=1}"
: "${ROBOMITUBA_RENDER_INPROCESS:=0}"
: "${PYTHONUNBUFFERED:=1}"

export ROBOMITUBA_MITSUBA_PYTHON
export ROBOMITUBA_MITSUBA_PYTHONPATH
export ROBOMITUBA_RENDER_GPU_INDICES
export ROBOMITUBA_FULL_RENDER_DISABLE_CUDA
export ROBOMITUBA_DISABLE_CPU_FALLBACK
export ROBOMITUBA_CPU_SPP_CAP
export ROBOMITUBA_TEXTURE_MAX_RESOLUTION
export ROBOMITUBA_WORKER_HEARTBEAT_TIMEOUT_S
export ROBOMITUBA_SCENE_LOAD_CONCURRENCY
export ROBOMITUBA_RENDER_INPROCESS
export PYTHONUNBUFFERED

exec python -u "$REPO_ROOT/apps/run_render_daemon.py" "$@"
