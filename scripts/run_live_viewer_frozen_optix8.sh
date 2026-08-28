#!/usr/bin/env bash
set -euo pipefail

# Device 1 / OptiX 8 frozen live viewer. It uses upstream dr.freeze rather
# than a private C++ binding and never starts dataset-render workers.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR:=$REPO_ROOT/modules/mitsuba3}"
: "${ROBOMITUBA_LIVE_FREEZE_BUILD_DIR:=/home/jinnyeong/robomituba-build/mitsuba3}"
: "${ROBOMITUBA_MITSUBA_PYTHON:=/usr/bin/python3}"
: "${ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX:=0}"
: "${ROBOMITUBA_LIVE_PREVIEW_PORT:=8767}"
: "${ROBOMITUBA_LIVE_PREVIEW_WIDTH:=640}"
: "${ROBOMITUBA_LIVE_PREVIEW_HEIGHT:=360}"
: "${ROBOMITUBA_LIVE_PREVIEW_SPP:=1}"
: "${ROBOMITUBA_LIVE_PREVIEW_MAX_DEPTH:=4}"

if [[ ! -f "$ROBOMITUBA_LIVE_FREEZE_BUILD_DIR/setpath.sh" ]]; then
  echo "[live-frozen-optix8] build missing: $ROBOMITUBA_LIVE_FREEZE_BUILD_DIR" >&2
  echo "[live-frozen-optix8] set ROBOMITUBA_LIVE_FREEZE_BUILD_DIR to a host-local OptiX 8 Mitsuba build" >&2
  exit 2
fi

export CUDA_VISIBLE_DEVICES="$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX"
export ROBOMITUBA_RENDER_INPROCESS=1
export ROBOMITUBA_MITSUBA_VARIANT=cuda_rgb
export ROBOMITUBA_DISABLE_CPU_FALLBACK=1
export ROBOMITUBA_MITSUBA_PYTHONPATH="$ROBOMITUBA_LIVE_FREEZE_BUILD_DIR/python"
export ROBOMITUBA_LIVE_PREVIEW_RENDERER=frozen
export PYTHONPATH="$REPO_ROOT/modules/mitsuba_converter/src:$REPO_ROOT/modules/robomituba_bridge/src:${ROBOMITUBA_MITSUBA_PYTHONPATH}:${PYTHONPATH:-}"
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"
export PYTHONUNBUFFERED=1
export PYTHONFAULTHANDLER=1

source "$REPO_ROOT/scripts/live_viewer_runtime.sh"
live_viewer_reserve_gpu "$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX" frozen-optix8
live_viewer_require_cuda_driver_api "$ROBOMITUBA_MITSUBA_PYTHON" 12020
live_viewer_log_git_revision mitsuba "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR"
live_viewer_log_git_revision drjit "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR/ext/drjit"
live_viewer_log_git_revision drjit_core "$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR/ext/drjit/ext/drjit-core"

"$ROBOMITUBA_MITSUBA_PYTHON" - <<'PY'
import drjit as dr
import mitsuba as mi

required = {"scalar_rgb", "cuda_rgb"}
missing = required.difference(mi.variants())
if missing:
    raise SystemExit(f"[live-frozen-optix8] build is missing variants: {sorted(missing)}")
if not dr.has_backend(dr.JitBackend.CUDA):
    raise SystemExit("[live-frozen-optix8] Dr.Jit CUDA backend is inactive")
mi.set_variant("cuda_rgb")
scene = mi.load_dict({
    "type": "scene",
    "integrator": {"type": "path", "max_depth": 1},
    "sensor": {"type": "perspective", "sampler": {"type": "independent", "sample_count": 1}, "film": {"type": "hdrfilm", "width": 1, "height": 1}},
    "shape": {"type": "sphere", "bsdf": {"type": "pplastic"}},
})
frozen = dr.freeze(lambda active_scene: mi.render(active_scene, spp=1), backend=dr.JitBackend.CUDA, limit=1)
first = frozen(scene); dr.eval(first)
second = frozen(scene); dr.eval(second)
recordings = frozen.n_recordings
third = frozen(scene); dr.eval(third)
if frozen.n_recordings != recordings:
    raise SystemExit("[live-frozen-optix8] Dr.Jit freeze replay retraced after warm-up")
if "cuda_rgb_polarized" in mi.variants():
    mi.set_variant("cuda_rgb_polarized")
    for bsdf in ("pplastic", "roughconductor", "dielectric"):
        mi.load_dict({"type": bsdf})
    print("[live-frozen-optix8] OptiX 8 + upstream Dr.Jit frozen replay + polarized BSDF smoke passed")
else:
    print("[live-frozen-optix8] OptiX 8 + upstream Dr.Jit frozen replay smoke passed; cuda_rgb_polarized is not in this live RGB build")
PY

echo "[live-frozen-optix8] mode=frozen GPU=$ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX port=$ROBOMITUBA_LIVE_PREVIEW_PORT variant=cuda_rgb build=$ROBOMITUBA_LIVE_FREEZE_BUILD_DIR"
echo "[live-frozen-optix8] profile=${ROBOMITUBA_LIVE_PREVIEW_WIDTH}x${ROBOMITUBA_LIVE_PREVIEW_HEIGHT} spp=${ROBOMITUBA_LIVE_PREVIEW_SPP} depth=${ROBOMITUBA_LIVE_PREVIEW_MAX_DEPTH}"
LIVE_LOG="${ROBOMITUBA_LIVE_PREVIEW_LOG:-/tmp/robomituba-live-viewer-${ROBOMITUBA_LIVE_PREVIEW_PORT}.log}"
echo "[live-frozen-optix8] log=$LIVE_LOG"
set +e
"$ROBOMITUBA_MITSUBA_PYTHON" -u "$REPO_ROOT/apps/run_render_daemon.py" \
  --repo-root "$REPO_ROOT" --host 0.0.0.0 --port "$ROBOMITUBA_LIVE_PREVIEW_PORT" --variant cuda_rgb 2>&1 | tee -a "$LIVE_LOG"
status=${PIPESTATUS[0]}
set -e
echo "[live-frozen-optix8] daemon exited status=$status; log retained at $LIVE_LOG" >&2
exit "$status"
