#!/usr/bin/env bash
# Spawn a Codex session as IR_DATASET_VIEWER_ORCHESTER.
# Run from any host where `codex` works. Sandbox mode is the runner's choice:
#   default here is danger-full-access because bwrap cannot pivot_root on Device 2.
set -euo pipefail
ROOT=/jarvis/project/robomituba
HERE="$ROOT/.agents/Scene_Scale_InverseRendering/orchesters/IR_DATASET_VIEWER_ORCHESTER"
MODEL="${CODEX_MODEL:-gpt-5.6-terra}"
EFFORT="${CODEX_EFFORT:-medium}"
SANDBOX="${CODEX_SANDBOX:-danger-full-access}"
LOG="$HERE/logs/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$LOG"
cd "$ROOT"
codex exec -m "$MODEL" -c model_reasoning_effort="$EFFORT" -s "$SANDBOX" -C "$ROOT" \
  --json -o "$LOG/last_message.md" - < "$HERE/spawn_prompt.md" \
  > "$LOG/events.jsonl" 2> "$LOG/stderr.log"
echo "exit=$? log=$LOG"; tail -20 "$LOG/last_message.md"
