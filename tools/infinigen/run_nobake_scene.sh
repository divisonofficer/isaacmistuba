#!/usr/bin/env bash
# One Infinigen 2.0 apartment through the no-bake path: prep (GT AOVs, IR_Band, flash) -> adapter (lit + flash-only) -> hover/walk
# render at 512x384 via apps/render_hssd_ir_passes.py (the same lit/flash/merge/depth-gate the v1 corpus worker runs, minus the bake).
#   tools/infinigen/run_nobake_scene.sh SCENE_ID SOURCE_BLEND OUT_ROOT GPU [hover_poses hover_seqs walk_poses walk_seqs]
set -euo pipefail
S=$1; SRC=$2; ROOT=$3; GPU=$4
HP=${5:-160}; HS=${6:-16}; WP=${7:-440}; WS=${8:-8}
REPO=/jarvis/project/robomituba; W=${NOBAKE_WORK:-/tmp/nobake_work}/$S
mkdir -p "$W" "$ROOT/$S"
cd "$REPO"
B=tools/infinigen/run_bundled_blender.py
if [ ! -f "$W/prepped.blend" ]; then
  CUDA_VISIBLE_DEVICES= python3 $B -t 8 --background "$SRC" --python-exit-code 1 \
    --python tools/infinigen/prepare_nobake_ir_scene.py -- --out "$W/prepped.blend"
fi
for kind in lit flash; do
  [ -f "$W/$S.$kind.blend" ] && continue
  extra=(); [ "$kind" = flash ] && extra=(--flash-only)
  CUDA_VISIBLE_DEVICES= python3 $B --background "$W/prepped.blend" --python-exit-code 1 \
    --python tools/infinigen/adapt_stage2_for_hssd_renderer.py -- --out "$W/$S.$kind.blend" "${extra[@]}"
done
export CUDA_VISIBLE_DEVICES=$GPU HSSD_IR_HOVER_FLOOR_BAND_M=1.00,1.50 HSSD_IR_PERSISTENT_DATA=1 \
       HSSD_IR_COMPUTE_DEVICE=OPTIX HSSD_IR_DENOISE_GPU=1 HSSD_IR_BAND_BATCH=1000
for m in "hover object_hover $HP $HS" "walk walking $WP $WS"; do
  set -- $m
  python3 apps/render_hssd_ir_passes.py --resume --stage --stage-dir "${HSSD_IR_STAGE_ROOT:-/tmp/hssd_ir_stage}/${1}_$S" \
    --lit-blend "$W/$S.lit.blend" --flash-blend "$W/$S.flash.blend" --out "$ROOT/$S/$1" \
    --pose-mode "$2" --pose-count "$3" --sequences "$4" \
    --width 512 --height 384 --spp 192 --nir-spp 192 --max-bounces 4 --threads 8
done
echo "NOBAKE_SCENE_DONE $S"
