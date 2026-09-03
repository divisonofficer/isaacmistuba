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
# Keep the delegated optix7 launcher's build banner pointing at the same build
# this script selects, so the log never advertises a build we do not load.
export ROBOMITUBA_DEVICE1_MITSUBA_BUILD_DIR="${ROBOMITUBA_DEVICE1_MITSUBA_BUILD_DIR:-/home/jinnyeong/robomituba-build/mitsuba3-v391}"
# Default to the 3.9.1 build. The older 3.7.1 build renders correctly but its
# BatchSensor predates upstream's function-freezing support, so frozen K-view
# Stokes strips there die with CUDA_ERROR_ILLEGAL_ADDRESS after a few replays
# (verified: 3.9.1 sustains 20 consecutive replays at 4 s per K=4 strip).
# Point this at .../mitsuba3/python to fall back to the 3.7.1 build.
export ROBOMITUBA_MITSUBA_PYTHONPATH="${ROBOMITUBA_MITSUBA_PYTHONPATH:-/home/jinnyeong/robomituba-build/mitsuba3-v391/python}"
# WSL OptiX/CUDA libs — inherited by the worker subprocess.
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"
# Single-GPU main-PC defaults (override for multi-GPU; or pass --auto-gpus).
export ROBOMITUBA_RENDER_GPU_INDICES="${ROBOMITUBA_RENDER_GPU_INDICES:-0}"
export ROBOMITUBA_RENDER_WORKER_COUNT="${ROBOMITUBA_RENDER_WORKER_COUNT:-1}"
export ROBOMITUBA_OPTIX_DENOISE=0
# Keep the reusable RGB base scene resident, but evict per-heading polarization
# staged scenes quickly. The default renderer limit (32) can retain many heavy
# polar XML variants during mixed RGB+polar rig sweeps on a single GPU.
export ROBOMITUBA_SCENE_CACHE_LIMIT="${ROBOMITUBA_SCENE_CACHE_LIMIT:-2}"
# Dr.Jit function freezing (dr.freeze) for the resident heading-batch and
# camera-aligned polar hot paths in multimodal.py::_render_scene. Only the
# OptiX 8 build (this script) exposes dr.freeze reliably -- the OptiX 7 build
# (run_render_queue_optix7.sh) segfaults inside it, so that script leaves this
# unset (default off). Override with ROBOMITUBA_RENDER_DRJIT_FREEZE=0 to
# compare against classic re-tracing on this device.
export ROBOMITUBA_RENDER_DRJIT_FREEZE="${ROBOMITUBA_RENDER_DRJIT_FREEZE:-1}"
# Textures dominate resident VRAM on these Infinigen apartments: ~1974 unique
# maps, and at the 1024 cap the float32 RGB footprint is ~10 GB, which pushed a
# 32 GB card into CUDA_ERROR_OUT_OF_MEMORY mid-sweep. ~78% of the maps are
# already 512, so capping here reclaims ~4 GB by downsampling only the 1024
# minority. These scenes use analytic BRDFs (no measured pBRDF), so texture
# resolution -- not BSDF data -- is the lever that matters.
export ROBOMITUBA_TEXTURE_MAX_RESOLUTION="${ROBOMITUBA_TEXTURE_MAX_RESOLUTION:-512}"


if [[ ! -d "$ROBOMITUBA_MITSUBA_PYTHONPATH" ]]; then
  echo "[render-queue-local] WARNING: Mitsuba build not found at $ROBOMITUBA_MITSUBA_PYTHONPATH" >&2
  echo "[render-queue-local]   set ROBOMITUBA_MITSUBA_PYTHONPATH=<your mitsuba3/python> to override." >&2
fi

# Report (and sanity-check) the renderer this launcher actually binds to.
# Renderer version is not cosmetic here: dr.freeze correctness depends on it.
# Upstream added batch-sensor function-freezing support in Mitsuba 3.8.0, and
# Dr.Jit 1.2.0 fixed an OptiX SBT read-after-free -- exactly the class of bug
# that surfaces as CUDA_ERROR_ILLEGAL_ADDRESS a few frozen replays in. Print
# the versions on every launch so a crash report always carries them, and warn
# when freezing is enabled on a build predating the batch-sensor support.
MITSUBA_VERSION_REPORT="$(
  LD_LIBRARY_PATH="$LD_LIBRARY_PATH" PYTHONPATH="$ROBOMITUBA_MITSUBA_PYTHONPATH" \
  "$ROBOMITUBA_MITSUBA_PYTHON" -c 'import mitsuba, drjit; print(f"{mitsuba.__version__} {drjit.__version__}")' 2>/dev/null
)"
MITSUBA_VERSION="${MITSUBA_VERSION_REPORT%% *}"
DRJIT_VERSION="${MITSUBA_VERSION_REPORT##* }"
# `--dirty` rescans the whole worktree, which takes minutes on the CIFS mount
# and stalled this launcher before it ever bound a port. The commit alone is
# enough to identify the source revision here.
MITSUBA_SRC_REV="$(timeout 10 git -C "$REPO_ROOT/modules/mitsuba3" describe --tags --always 2>/dev/null || echo unknown)"
echo "[render-queue-local] renderer: mitsuba ${MITSUBA_VERSION:-unknown} · drjit ${DRJIT_VERSION:-unknown} · src ${MITSUBA_SRC_REV}"

# Minimum version whose upstream batch sensor implements freeze support.
: "${ROBOMITUBA_MITSUBA_MIN_FREEZE_VERSION:=3.8.0}"
if [[ "$ROBOMITUBA_RENDER_DRJIT_FREEZE" != "0" && -n "$MITSUBA_VERSION" ]]; then
  lowest="$(printf '%s\n%s\n' "$MITSUBA_VERSION" "$ROBOMITUBA_MITSUBA_MIN_FREEZE_VERSION" | sort -V | head -1)"
  if [[ "$lowest" == "$MITSUBA_VERSION" && "$MITSUBA_VERSION" != "$ROBOMITUBA_MITSUBA_MIN_FREEZE_VERSION" ]]; then
    echo "[render-queue-local] WARNING: mitsuba $MITSUBA_VERSION predates $ROBOMITUBA_MITSUBA_MIN_FREEZE_VERSION," >&2
    echo "[render-queue-local]   which is where upstream added batch-sensor freeze support. Frozen K-view" >&2
    echo "[render-queue-local]   Stokes batches may die with CUDA_ERROR_ILLEGAL_ADDRESS after a few replays." >&2
    echo "[render-queue-local]   Set ROBOMITUBA_RENDER_DRJIT_FREEZE=0 to run without freezing." >&2
  fi
fi
echo "[render-queue-local] using standard build: $ROBOMITUBA_MITSUBA_PYTHON + $ROBOMITUBA_MITSUBA_PYTHONPATH"
echo "[render-queue-local] Dr.Jit freeze (resident hot paths): $ROBOMITUBA_RENDER_DRJIT_FREEZE"

exec bash "$REPO_ROOT/scripts/run_render_queue_optix7.sh" "$@"
