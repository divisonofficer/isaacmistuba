#!/bin/bash
# Dataset render with one automatic retry on the hover merge refusal ("two runs did not select the same poses"):
# rerun asking for exactly the first run's sequences/poses (the fix that worked for CS01/CS05/PH02/PH12).
# usage: promote_auto.sh GPU WAIT_PATTERN LOCKFILE|- SCENE BLEND [ENV...]
G=$1; WAIT=$2; L=$3; S=$4; B=$5; shift 5
O=/tmp/claude-0/objreal; ROOT=/bean/ir_dataset_work/hssd_ir_apartment_v2
while pgrep -f "$WAIT" >/dev/null; do sleep 300; done
export NOBAKE_WORK=/bean/ir_dataset_work/infinigen_v2_nobake_work HSSD_IR_STAGE_ROOT=/bean/ir_dataset_work/hssd_ir_stage_nonhome
cd /jarvis/project/robomituba
go() { if [ "$L" = - ]; then env "$@"; else flock "$L" env "$@"; fi; }
go "$@" timeout 20h $O/run_nobake_scene_band.sh $S $B $ROOT $G 320 32 960 32 > $O/dataset_$S.log 2>&1 && { echo "$(date -u +%FT%TZ) DONE $S"; exit 0; }
if grep -q "did not select the same poses" $O/dataset_$S.log; then
  read SEQ POS < <(grep -oE '"event": "hover_poses", "sequences": [0-9]+, "poses": [0-9]+' $O/dataset_$S.log | head -1 | grep -oE '[0-9]+' | tr '\n' ' ')
  echo "$(date -u +%FT%TZ) RETRY $S hover $POS/$SEQ"
  go "$@" timeout 20h $O/run_nobake_scene_band.sh $S $B $ROOT $G $POS $SEQ 960 32 > $O/dataset_${S}_retry.log 2>&1 && echo "$(date -u +%FT%TZ) DONE $S" || echo "$(date -u +%FT%TZ) FAILED $S (retry)"
else echo "$(date -u +%FT%TZ) FAILED $S"; fi
