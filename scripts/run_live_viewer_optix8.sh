#!/usr/bin/env bash
set -euo pipefail

# Device 1 / OptiX 8 classic reference viewer. Use a separate process from
# the frozen viewer; the shared GPU lock makes a one-GPU host choose one mode.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${ROBOMITUBA_MITSUBA_BUILD_DIR:=/home/jinnyeong/robomituba-build/mitsuba3}"
: "${ROBOMITUBA_MITSUBA_PYTHON:=/usr/bin/python3}"
: "${ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX:=0}"
: "${ROBOMITUBA_LIVE_PREVIEW_PORT:=8766}"
: "${ROBOMITUBA_LIVE_PREVIEW_WIDTH:=640}"
: "${ROBOMITUBA_LIVE_PREVIEW_HEIGHT:=360}"
: "${ROBOMITUBA_LIVE_PREVIEW_SPP:=1}"

if [[ ! -f "$ROBOMITUBA_MITSUBA_BUILD_DIR/setpath.sh" ]]; then
  echo "[live-viewer-optix8] build missing: $ROBOMITUBA_MITSUBA_BUILD_DIR" >&2
  exit 2
fi

export CUDA_VISIBLE_DEVICES="$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX"
export ROBOMITUBA_RENDER_INPROCESS=1
export ROBOMITUBA_MITSUBA_VARIANT=cuda_rgb
export ROBOMITUBA_DISABLE_CPU_FALLBACK=1
export ROBOMITUBA_MITSUBA_PYTHONPATH="$ROBOMITUBA_MITSUBA_BUILD_DIR/python"
export ROBOMITUBA_LIVE_PREVIEW_RENDERER=classic
export PYTHONPATH="$REPO_ROOT/modules/mitsuba_converter/src:$REPO_ROOT/modules/robomituba_bridge/src:${ROBOMITUBA_MITSUBA_PYTHONPATH}:${PYTHONPATH:-}"
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"
export PYTHONUNBUFFERED=1
export PYTHONFAULTHANDLER=1

source "$REPO_ROOT/scripts/live_viewer_runtime.sh"
live_viewer_reserve_gpu "$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX" classic-optix8
live_viewer_log_git_revision mitsuba "$REPO_ROOT/modules/mitsuba3"
live_viewer_log_git_revision drjit "$REPO_ROOT/modules/mitsuba3/ext/drjit"

"$ROBOMITUBA_MITSUBA_PYTHON" - <<'PY'
import drjit as dr
import mitsuba as mi

if "cuda_rgb" not in mi.variants():
    raise SystemExit("[live-viewer-optix8] build is missing cuda_rgb")
mi.set_variant("cuda_rgb")
if not dr.has_backend(dr.JitBackend.CUDA):
    raise SystemExit("[live-viewer-optix8] Dr.Jit CUDA backend is inactive")
print("[live-viewer-optix8] cuda_rgb + Dr.Jit CUDA smoke passed")
PY

echo "[live-viewer-optix8] mode=classic GPU=$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX port=$ROBOMITUBA_LIVE_PREVIEW_PORT variant=cuda_rgb build=$ROBOMITUBA_MITSUBA_BUILD_DIR"
LIVE_LOG="${ROBOMITUBA_LIVE_PREVIEW_LOG:-/tmp/robomituba-live-viewer-${ROBOMITUBA_LIVE_PREVIEW_PORT}.log}"
set +e
"$ROBOMITUBA_MITSUBA_PYTHON" -u "$REPO_ROOT/apps/run_render_daemon.py" \
  --repo-root "$REPO_ROOT" --host 0.0.0.0 --port "$ROBOMITUBA_LIVE_PREVIEW_PORT" --variant cuda_rgb 2>&1 | tee -a "$LIVE_LOG"
status=${PIPESTATUS[0]}
set -e
echo "[live-viewer-optix8] daemon exited status=$status; log retained at $LIVE_LOG" >&2
exit "$status"
