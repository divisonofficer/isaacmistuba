#!/usr/bin/env bash
set -euo pipefail

# Local main-PC variant of run_render_queue_optix7.sh.
#
# The optix7 script hardcodes the optix7 rig's conda interpreter
# (/root/miniconda3/envs/mitsuba_optix7/bin/python) and the production OptiX7
# build (build/mitsuba3-optix7/python) — neither exists on the main PC, so it
# dies with "Permission denied: /root/miniconda3/...".
#
# This wrapper points the Mitsuba render worker at the *standard validation
# build* (/home/jinnyeong/robomituba-build/mitsuba3, python3.10) instead, adds
# the WSL OptiX/CUDA libs, picks single-GPU defaults, then delegates to the same
# render-queue launcher. The optix7 script reads every var with `:=`, so these
# exports win; everything else (args like --auto-gpus, ports, GPU discovery)
# behaves identically.
#
# Usage (same flags as the optix7 script):
#   bash scripts/run_render_queue_local.sh
#   RENDER_QUEUE_PORT=8765 bash scripts/run_render_queue_local.sh   # all-in-one
#   ROBOMITUBA_RENDER_GPU_INDICES=0,1 bash scripts/run_render_queue_local.sh
#
# NOTE: the standard build lacks the optix7-only `measured_polarized_rgb`
# plugin, so measured-pBRDF metals fall back to gray (Phase 0). Mirror/glass/
# diffuse render correctly.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Mitsuba worker interpreter + build — the standard build, overridable via env.
export ROBOMITUBA_MITSUBA_PYTHON="${ROBOMITUBA_MITSUBA_PYTHON:-/usr/bin/python3.10}"
export ROBOMITUBA_MITSUBA_PYTHONPATH="${ROBOMITUBA_MITSUBA_PYTHONPATH:-/home/jinnyeong/robomituba-build/mitsuba3/python}"
# WSL OptiX/CUDA libs — inherited by the worker subprocess.
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"
# Single-GPU main-PC defaults (override for multi-GPU; or pass --auto-gpus).
export ROBOMITUBA_RENDER_GPU_INDICES="${ROBOMITUBA_RENDER_GPU_INDICES:-0}"
export ROBOMITUBA_RENDER_WORKER_COUNT="${ROBOMITUBA_RENDER_WORKER_COUNT:-1}"

if [[ ! -d "$ROBOMITUBA_MITSUBA_PYTHONPATH" ]]; then
  echo "[render-queue-local] WARNING: Mitsuba build not found at $ROBOMITUBA_MITSUBA_PYTHONPATH" >&2
  echo "[render-queue-local]   set ROBOMITUBA_MITSUBA_PYTHONPATH=<your mitsuba3/python> to override." >&2
fi
echo "[render-queue-local] using standard build: $ROBOMITUBA_MITSUBA_PYTHON + $ROBOMITUBA_MITSUBA_PYTHONPATH"

exec bash "$REPO_ROOT/scripts/run_render_queue_optix7.sh" "$@"
