#!/usr/bin/env bash
# One Infinigen 2.0 apartment end to end (2026-10-13):
#   generate (fork fast solver, vanilla config, solve_small off) -> 2.0 room materials -> activity pass (surfaces, palette, art)
#   -> no-bake GT render (hover + walk, 512x384) into the infinigen_2.0 corpus.
#   tools/infinigen/build_v2_scene.sh SEED GPU [OUT_ROOT]      env: ABO=1 (ABO decor), PLAN=1 (LLM room plans), NO_MEDIUM=1 (LLM
#   replaces solve_medium: chairs, side tables, lamps, plants), SKIP_RENDER=1
# Every step skips when its output exists, so a rerun resumes. Logs: $W/*.log
set -euo pipefail
SEED=$1; GPU=$2; ROOT=${3:-/bean/ir_dataset_work/hssd_ir_apartment_v2}
REPO=/jarvis/project/robomituba; cd "$REPO"
W=$REPO/out/infinigen_v2/kr_$SEED; F=$W/full; mkdir -p "$F"
# v2_1 = LLM-furnished (PLAN=1: room_planner + lived-in + ABO ceiling fixtures); "v2.1" without the dot, which Path.suffix would eat
VER=${VER:-$([ "${PLAN:-0}" = 1 ] && echo v2_1 || echo v2a)}
SCENE=infinigen_apartment_natural_${VER}_$SEED
IGPY=/root/miniconda3/envs/infinigen/bin/python

if [ ! -f "$F/scene.blend" ]; then
  # the fork, not /root/module (the env's install), holds fast_solve_config
  # MPLBACKEND: DISPLAY=:99 (Xvfb) makes matplotlib pick TkAgg; Tk objects GC'd off the main thread abort Infinigen (SIGABRT,
  # "Tcl_AsyncDelete: async handler deleted by the wrong thread", 35718226 2026-10-15)
  MPLBACKEND=Agg PYTHONPATH=$REPO/modules/infinigen python3 scripts/infinigen_gen.py --seed "$SEED" --density normal_lived_in \
    --floor-plan apartment_natural_v1 --anchor-richness balanced --surface-clutter balanced \
    --placement-profile collision_aware_clutter_v1 --stage full --base-config vanilla --small-objects activity --out "$F" \
    -p fast_solve_config.placeholder_reuse=3 -p fast_solve_config.factory_fail_limit=8 -p fast_solve_config.stall_limit=30 \
    -p fast_solve_config.memo_parent_footprint=True ${NO_MEDIUM:+-p compose_indoors.solve_medium_enabled=False} \
    -p populate_doors.casing_chance=1.0 --run > "$W/gen.log" 2>&1
fi
if [ ! -f "$F/scene_mat2.blend" ]; then
  CUDA_VISIBLE_DEVICES= python3 tools/infinigen/run_bundled_blender.py -t 8 --background "$F/scene.blend" --python-exit-code 1 \
    --python tools/infinigen/rematerial_rooms_infinigen2.py -- --out "$F/scene_mat2.blend" --seed "$SEED" > "$W/rematerial.log" 2>&1
fi
if [ "${PLAN:-0}" = 1 ] && [ ! -f "$F/scene_mat2_activity.blend" ] && [ ! -f "$F/plans.json" ]; then
  # LLM room plans (Claude Sonnet 5.5; key: ANTHROPIC_API_KEY or ~/.config/robomituba/anthropic_key), realized by the activity pass
  (cd /tmp && CUDA_VISIBLE_DEVICES= $IGPY "$REPO/tools/infinigen/room_planner/extract_rooms.py" "$F/scene_mat2.blend" \
     --out "$F/rooms.json") > "$W/plan.log" 2>&1
  (cd "$REPO/tools/infinigen" && /root/miniconda3/bin/python3 -m room_planner.plan_scene "$F/rooms.json" --out "$F/plans.json.tmp" \
     --seed "$SEED") >> "$W/plan.log" 2>&1 && mv "$F/plans.json.tmp" "$F/plans.json"
fi
if [ ! -f "$F/scene_mat2_activity.blend" ]; then
  PLANS=; [ "${PLAN:-0}" = 1 ] && PLANS="--plans $F/plans.json"
  (cd /tmp && CUDA_VISIBLE_DEVICES= $IGPY "$REPO/tools/infinigen/activity_pass_infinigen2.py" "$F/scene_mat2.blend" \
     --out "$F/scene_mat2_activity.blend" --solve-state "$F/solve_state.json" --seed "$SEED" ${ABO:+--abo} $PLANS) > "$W/activity.log" 2>&1 \
    || grep -q '^ACTIVITY' "$W/activity.log"     # with ABO imports Blender can segfault at exit, after the save and the summary line
fi
[ "${SKIP_RENDER:-0}" = 1 ] && { echo "BUILD_V2_GENERATED $SCENE"; exit 0; }     # campaign: generate now, render from the queue
if [ -f "$ROOT/$SCENE/hover/four_pass.json" ] && [ -f "$ROOT/$SCENE/walk/four_pass.json" ]; then echo "BUILD_V2_ALREADY_RENDERED $SCENE"; exit 0; fi
mkdir "$W/render.lock" 2>/dev/null || { echo "BUILD_V2_RENDER_BUSY $SCENE"; exit 0; }   # another worker renders it
trap 'rmdir "$W/render.lock"' EXIT
NOBAKE_WORK=${NOBAKE_WORK:-/tmp/claude-0/nobake_work} tools/infinigen/run_nobake_scene.sh "$SCENE" "$F/scene_mat2_activity.blend" \
  "$ROOT" "$GPU" 160 16 440 8 > "$W/nobake.log" 2>&1
echo "BUILD_V2_DONE $SCENE"
