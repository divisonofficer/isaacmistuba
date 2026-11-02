#!/usr/bin/env bash
# A batch of Infinigen 2.0 apartments (2026-10-13): generate P at a time (CPU), render one at a time on GPU, in seed order.
#   tools/infinigen/v2_campaign.sh GPU P SEED...      (WAIT_PID=<pid>: the render queue starts after that process exits)
# Logs: out/infinigen_v2/campaign/{gen,render}.log (one line per seed + exit code), per-seed *.out
set -uo pipefail
GPU=$1; P=$2; shift 2
REPO=/jarvis/project/robomituba; cd "$REPO"
LOG=$REPO/out/infinigen_v2/campaign; mkdir -p "$LOG"
printf '%s\n' "$@" | xargs -P "$P" -I{} sh -c \
  'SKIP_RENDER=1 timeout 6h tools/infinigen/build_v2_scene.sh {} - > out/infinigen_v2/campaign/gen_{}.out 2>&1; echo "gen {} $?"' \
  >> "$LOG/gen.log" &
while [ -n "${WAIT_PID:-}" ] && kill -0 "$WAIT_PID" 2>/dev/null; do sleep 60; done
for s in "$@"; do
  until [ -f "out/infinigen_v2/kr_$s/full/scene_mat2_activity.blend" ]; do
    grep -qE "^gen $s [1-9]" "$LOG/gen.log" && break           # generation failed: skip it
    sleep 60
  done
  [ -f "out/infinigen_v2/kr_$s/full/scene_mat2_activity.blend" ] || { echo "render $s skipped_no_blend" >> "$LOG/render.log"; continue; }
  timeout 10h tools/infinigen/build_v2_scene.sh "$s" "$GPU" > "$LOG/render_$s.out" 2>&1
  echo "render $s $?" >> "$LOG/render.log"
done
wait
echo CAMPAIGN_DONE >> "$LOG/render.log"
