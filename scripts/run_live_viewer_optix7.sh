#!/usr/bin/env bash
set -euo pipefail

# A dedicated, in-process Mitsuba daemon for the OpticalNav live viewer.
# Do not run dataset workers in this process: CUDA_VISIBLE_DEVICES reserves one
# GPU so viewer JIT state and measured BSDF allocations cannot contend with a
# sweep worker.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${ROBOMITUBA_MITSUBA_BUILD_DIR:?Set this to the host-local mitsuba3-optix7 build}"
: "${ROBOMITUBA_MITSUBA_PYTHON:=/root/miniconda3/envs/mitsuba_optix7/bin/python}"
: "${ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX:=7}"
: "${ROBOMITUBA_LIVE_PREVIEW_PORT:=8766}"
: "${ROBOMITUBA_LIVE_PREVIEW_WIDTH:=640}"
: "${ROBOMITUBA_LIVE_PREVIEW_HEIGHT:=360}"
: "${ROBOMITUBA_LIVE_PREVIEW_SPP:=1}"

export CUDA_VISIBLE_DEVICES="$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX"
export ROBOMITUBA_RENDER_INPROCESS=1
export ROBOMITUBA_MITSUBA_VARIANT=cuda_rgb
export ROBOMITUBA_DISABLE_CPU_FALLBACK=1
export ROBOMITUBA_MITSUBA_PYTHONPATH="${ROBOMITUBA_MITSUBA_BUILD_DIR}/python"
export PYTHONPATH="$REPO_ROOT/modules/mitsuba_converter/src:$REPO_ROOT/modules/robomituba_bridge/src:${ROBOMITUBA_MITSUBA_PYTHONPATH}:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
export PYTHONFAULTHANDLER=1

source "$REPO_ROOT/scripts/live_viewer_runtime.sh"
live_viewer_reserve_gpu "$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX" classic

"$ROBOMITUBA_MITSUBA_PYTHON" - <<PY
import os
from pathlib import Path
import mitsuba as mi

if "cuda_rgb" not in mi.variants():
    raise SystemExit(
        "cuda_rgb is not compiled in the host-local Mitsuba build. Reconfigure "
        "the Device 2 build with -DMI_DEFAULT_VARIANTS='scalar_rgb;scalar_spectral;cuda_rgb;cuda_ad_rgb;llvm_ad_rgb' and rebuild."
    )
mi.set_variant("cuda_rgb")
sample = Path("$REPO_ROOT/data/pbrdf_2020/mitsuba/4_black_billiard_inpainted.pbsdf")
if sample.is_file():
    # The scalar measured plugin needs an explicit band in non-spectral RGB
    # mode. Full measured RGB composition remains the dataset renderer's job.
    mi.load_dict({"type": "measured_polarized", "filename": str(sample), "wavelength": 542.0})
    print("[live-viewer] cuda_rgb + measured_polarized smoke passed")
else:
    print("[live-viewer] cuda_rgb smoke passed; measured-polarized sample is absent, skipping plugin smoke")
PY

echo "[live-viewer] mode=classic GPU=$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX port=$ROBOMITUBA_LIVE_PREVIEW_PORT variant=cuda_rgb build=$ROBOMITUBA_MITSUBA_BUILD_DIR"
echo "[live-viewer] profile=${ROBOMITUBA_LIVE_PREVIEW_WIDTH}x${ROBOMITUBA_LIVE_PREVIEW_HEIGHT} spp=${ROBOMITUBA_LIVE_PREVIEW_SPP} depth=${ROBOMITUBA_LIVE_PREVIEW_MAX_DEPTH:-4}"
LIVE_LOG="${ROBOMITUBA_LIVE_PREVIEW_LOG:-/tmp/robomituba-live-viewer-${ROBOMITUBA_LIVE_PREVIEW_PORT}.log}"
echo "[live-viewer] log=$LIVE_LOG"
set +e
"$ROBOMITUBA_MITSUBA_PYTHON" -u "$REPO_ROOT/apps/run_render_daemon.py" \
  --repo-root "$REPO_ROOT" --host 0.0.0.0 --port "$ROBOMITUBA_LIVE_PREVIEW_PORT" --variant cuda_rgb 2>&1 | tee -a "$LIVE_LOG"
DAEMON_STATUS=${PIPESTATUS[0]}
set -e
echo "[live-viewer] daemon exited status=$DAEMON_STATUS; log retained at $LIVE_LOG" >&2
exit "$DAEMON_STATUS"
