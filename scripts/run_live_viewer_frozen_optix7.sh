#!/usr/bin/env bash
set -euo pipefail

# Host-local, upstream-pinned Mitsuba/Dr.Jit build used only by the XML frozen viewer.
# The legacy Device 2 build and normal render daemon intentionally remain
# untouched. Build it first with scripts/build_live_frozen_mitsuba_optix7.sh.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${ROBOMITUBA_LIVE_FREEZE_BUILD_DIR:=/root/robomituba-live-freeze/build}"
: "${ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR:=/root/robomituba-live-freeze/mitsuba3}"
: "${ROBOMITUBA_MITSUBA_PYTHON:=/root/miniconda3/envs/mitsuba_optix7/bin/python}"
: "${ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX:=6}"
: "${ROBOMITUBA_LIVE_PREVIEW_PORT:=8767}"
: "${ROBOMITUBA_LIVE_PREVIEW_WIDTH:=640}"
: "${ROBOMITUBA_LIVE_PREVIEW_HEIGHT:=360}"
: "${ROBOMITUBA_LIVE_PREVIEW_SPP:=1}"
: "${ROBOMITUBA_LIVE_PREVIEW_MAX_DEPTH:=4}"

if [[ ! -f "$ROBOMITUBA_LIVE_FREEZE_BUILD_DIR/setpath.sh" ]]; then
  echo "[live-frozen] build missing: $ROBOMITUBA_LIVE_FREEZE_BUILD_DIR" >&2
  echo "[live-frozen] run scripts/build_live_frozen_mitsuba_optix7.sh first" >&2
  exit 2
fi

export CUDA_VISIBLE_DEVICES="$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX"
export ROBOMITUBA_RENDER_INPROCESS=1
export ROBOMITUBA_MITSUBA_VARIANT=cuda_rgb
export ROBOMITUBA_DISABLE_CPU_FALLBACK=1
export ROBOMITUBA_MITSUBA_PYTHONPATH="$ROBOMITUBA_LIVE_FREEZE_BUILD_DIR/python"
export ROBOMITUBA_LIVE_PREVIEW_RENDERER=frozen
export PYTHONPATH="$REPO_ROOT/modules/mitsuba_converter/src:$REPO_ROOT/modules/robomituba_bridge/src:${ROBOMITUBA_MITSUBA_PYTHONPATH}:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
export PYTHONFAULTHANDLER=1

source "$REPO_ROOT/scripts/live_viewer_runtime.sh"
live_viewer_reserve_gpu "$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX" frozen
live_viewer_require_cuda_driver_api "$ROBOMITUBA_MITSUBA_PYTHON" 12020
live_viewer_log_git_revision mitsuba "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR"
live_viewer_log_git_revision drjit "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR/ext/drjit"
live_viewer_log_git_revision drjit_core "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR/ext/drjit/ext/drjit-core"

"$ROBOMITUBA_MITSUBA_PYTHON" - <<'PY'
import drjit as dr
import mitsuba as mi

required = {"scalar_rgb", "cuda_rgb", "cuda_ad_rgb", "cuda_rgb_polarized"}
missing = required.difference(mi.variants())
if missing:
    raise SystemExit(f"[live-frozen] build is missing variants: {sorted(missing)}")
if not dr.has_backend(dr.JitBackend.CUDA):
    raise SystemExit(
        "[live-frozen] Dr.Jit CUDA backend is inactive. "
        "Verify the R535+ host driver and rebuild the isolated upstream-pinned source."
    )
mi.set_variant("cuda_rgb")
if not hasattr(mi, "LiveFrozenRenderer"):
    raise SystemExit("[live-frozen] native LiveFrozenRenderer binding is absent; rerun the frozen build")
try:
    mi.load_dict({
        "type": "scene",
        "integrator": {"type": "path", "max_depth": 1},
        "sensor": {
            "type": "perspective",
            "sampler": {"type": "independent", "sample_count": 1},
            "film": {"type": "hdrfilm", "width": 1, "height": 1},
        },
        "shape": {"type": "sphere", "bsdf": {"type": "pplastic"}},
    })
except RuntimeError as exc:
    raise SystemExit(
        "[live-frozen] Dr.Jit CUDA is active but OptiX scene initialization failed. "
        "This newer Dr.Jit build requires an R535+ host driver.\n"
        f"Original error: {exc}"
    ) from exc
mi.set_variant("cuda_rgb_polarized")
for bsdf in ("pplastic", "roughconductor", "dielectric"):
    mi.load_dict({"type": bsdf})
print("[live-frozen] native bridge + cuda_rgb_polarized allowed-BSDF smoke passed")
PY

echo "[live-frozen] mode=frozen GPU=$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX port=$ROBOMITUBA_LIVE_PREVIEW_PORT variant=cuda_rgb build=$ROBOMITUBA_LIVE_FREEZE_BUILD_DIR"
echo "[live-frozen] profile=${ROBOMITUBA_LIVE_PREVIEW_WIDTH}x${ROBOMITUBA_LIVE_PREVIEW_HEIGHT} spp=${ROBOMITUBA_LIVE_PREVIEW_SPP} depth=${ROBOMITUBA_LIVE_PREVIEW_MAX_DEPTH}"
LIVE_LOG="${ROBOMITUBA_LIVE_PREVIEW_LOG:-/tmp/robomituba-live-viewer-${ROBOMITUBA_LIVE_PREVIEW_PORT}.log}"
echo "[live-frozen] log=$LIVE_LOG"
set +e
"$ROBOMITUBA_MITSUBA_PYTHON" -u "$REPO_ROOT/apps/run_render_daemon.py" \
  --repo-root "$REPO_ROOT" --host 0.0.0.0 --port "$ROBOMITUBA_LIVE_PREVIEW_PORT" --variant cuda_rgb 2>&1 | tee -a "$LIVE_LOG"
status=${PIPESTATUS[0]}
set -e
echo "[live-frozen] daemon exited status=$status; log retained at $LIVE_LOG" >&2
exit "$status"
