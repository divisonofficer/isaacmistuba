#!/usr/bin/env bash
# Extra GPU render worker for the 2.0 campaign (2026-10-13): renders every generated scene (activity blend present) that is neither
# rendered nor locked by another worker; build_v2_scene.sh holds the lock. Exits after IDLE_MIN minutes with nothing to take.
#   tools/infinigen/v2_render_worker.sh GPU SEED...
set -uo pipefail
GPU=$1; shift
failed=" "
REPO=/jarvis/project/robomituba; cd "$REPO"; LOG=$REPO/out/infinigen_v2/campaign; idle=0
while [ "$idle" -lt "${IDLE_MIN:-120}" ]; do
  took=0
  for s in "$@"; do
    W=out/infinigen_v2/kr_$s
    [ -f "/bean/ir_dataset_work/hssd_ir_apartment_v2/infinigen_apartment_natural_v2a_$s/walk/four_pass.json" ] && continue   # rendered
    [ -f "$W/full/scene_mat2_activity.blend" ] && [ ! -d "$W/render.lock" ] && [ "${failed/ $s /}" = "$failed" ] || continue
    out=$(timeout 10h tools/infinigen/build_v2_scene.sh "$s" "$GPU" 2>&1 | tail -1)
    echo "render $s worker_gpu$GPU ${out%% *}" >> "$LOG/render.log"
    case "$out" in BUILD_V2_DONE*) took=1;; BUILD_V2_ALREADY*|BUILD_V2_RENDER_BUSY*) ;; *) failed="$failed$s ";; esac   # one failure: leave it
  done
  [ $took = 1 ] && idle=0 || { idle=$((idle + 2)); sleep 120; }
done
