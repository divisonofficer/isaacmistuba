#!/usr/bin/env bash
set -euo pipefail

# Build the pinned HDMitsuba-compatible Mitsuba source in an isolated,
# host-local directory. Do not point this script at the legacy build.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR:=/root/robomituba-live-freeze/mitsuba3}"
: "${ROBOMITUBA_LIVE_FREEZE_BUILD_DIR:=/root/robomituba-live-freeze/build}"
: "${ROBOMITUBA_MITSUBA_PYTHON:=/root/miniconda3/envs/mitsuba_optix7/bin/python}"
export ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR

if [[ ! -f "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR/CMakeLists.txt" ]]; then
  echo "[live-frozen] source missing: $ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR" >&2
  echo "[live-frozen] expected Mitsuba commit 5eefc440f0a9d4f94e94a2794667397610cbfeda" >&2
  exit 2
fi
if ! rg -q 'LiveFrozenRenderer' "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR/src/python/main_v.cpp"; then
  echo "[live-frozen] native bridge patch has not been applied to host-local source" >&2
  exit 2
fi

# R535+ loads the upstream pinned Dr.Jit core's CUDA 12.2 PTX directly.  A
# CUDA-11.8/PTX-downlevel edit is an unsupported fork and must never be
# silently applied while producing the normal frozen-viewer build.
core_dir="$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR/ext/drjit/ext/drjit-core"
if ! git -C "$core_dir" diff --quiet -- resources/Makefile src/cuda_core.cpp; then
  echo "[live-frozen] Dr.Jit-core has CUDA/PTX fork edits. Use a clean pinned source for the R535+ build." >&2
  exit 2
fi

# The common render library in this pinned Mitsuba revision references the
# Dr.Jit AD runtime even for cuda_rgb. Keep cuda_ad_rgb compiled solely to
# link that runtime; the live viewer's release path remains cuda_rgb.
#
# Mitsuba only consumes MI_DEFAULT_VARIANTS while generating mitsuba.conf.
# That generated file can survive a reconfigure, so invalidate it when it
# still represents the pre-AD set; otherwise libmitsuba is linked without
# drjit-extra and fails on unresolved ad_* symbols.
if [[ -f "$ROBOMITUBA_LIVE_FREEZE_BUILD_DIR/mitsuba.conf" ]] \
  && ! rg -q '"cuda_ad_rgb"' "$ROBOMITUBA_LIVE_FREEZE_BUILD_DIR/mitsuba.conf"; then
  echo "[live-frozen] regenerating stale generated mitsuba.conf with cuda_ad_rgb"
  rm -f "$ROBOMITUBA_LIVE_FREEZE_BUILD_DIR/mitsuba.conf"
fi
cmake -S "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR" -B "$ROBOMITUBA_LIVE_FREEZE_BUILD_DIR" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DPython_EXECUTABLE="$ROBOMITUBA_MITSUBA_PYTHON" \
  -DDRJIT_DYNAMIC_CUDA=ON \
  -DMI_DEFAULT_VARIANTS='scalar_rgb;cuda_rgb;cuda_ad_rgb;cuda_rgb_polarized'
cmake --build "$ROBOMITUBA_LIVE_FREEZE_BUILD_DIR" --parallel "${ROBOMITUBA_LIVE_FREEZE_BUILD_JOBS:-4}"
source "$REPO_ROOT/scripts/live_viewer_runtime.sh"
live_viewer_log_git_revision mitsuba "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR"
live_viewer_log_git_revision drjit "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR/ext/drjit"
live_viewer_log_git_revision drjit_core "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR/ext/drjit/ext/drjit-core"
echo "[live-frozen] build complete: $ROBOMITUBA_LIVE_FREEZE_BUILD_DIR"
