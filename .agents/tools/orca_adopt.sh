#!/usr/bin/env bash
# orca_adopt.sh — move a fleet agent into an Orca-managed terminal.
#
# Orca (orca-ide) only sees agents that run inside its own terminals, so a
# session started from VS Code or `claude remote-control` cannot be registered
# after the fact. This creates an Orca terminal in the repo that resumes the
# agent's last session id (from .agents/tools/session_map.json), so the
# conversation context carries over. Refuses while another live process still
# holds that session id, because two processes on one transcript confuse peers
# and the Remote Control bridge. Close the VS Code copy first.
#
# Usage: orca_adopt.sh NAME [--force] [--dry-run]
# Env:   ORCA_WORKTREE  worktree selector (default path:$ROOT; e.g. name:OpticalNav)
set -euo pipefail
NAME="${1:?agent name}"; shift || true
FORCE=0; DRY=0
for a in "$@"; do case "$a" in --force) FORCE=1;; --dry-run) DRY=1;; esac; done
ROOT="${FLEET_ROOT:-/jarvis/project/robomituba}"
MAP="$ROOT/.agents/tools/session_map.json"
SID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],{}).get("sessionId") or "")' "$MAP" "$NAME")"
[ -n "$SID" ] || { echo "$NAME: no session id in $MAP; run ensure_sessions.sh --list while it is live, or adopt fresh with --force" >&2; [ "$FORCE" = 1 ] || exit 1; }
LIVE="$(python3 - "$SID" <<'PY'
import glob, json, os, sys
sid = sys.argv[1]
for f in glob.glob(os.path.expanduser("~/.claude/sessions/*.json")):
    try: d = json.load(open(f))
    except Exception: continue
    if sid and d.get("sessionId") == sid and os.path.exists(f"/proc/{d.get('pid')}"):
        print(f"{d['pid']} {d.get('entrypoint')} {d.get('name')}")
PY
)"
if [ "$DRY" = 1 ]; then echo "$NAME: sid=${SID:-none} live_elsewhere=${LIVE:-no}; would run: orca-ide terminal create --worktree ${ORCA_WORKTREE:-path:$ROOT} --title $NAME --command \"claude remote-control --name $NAME${SID:+ --session-id $SID}\" --json"; exit 0; fi
if [ -n "$LIVE" ] && [ "$FORCE" != 1 ]; then
  echo "$NAME: session $SID is still live elsewhere ($LIVE). Close it first, or --force to resume anyway." >&2; exit 2
fi
# Remote Control on by default (user rule 2026-09-21): launch through `claude remote-control`,
# which reattaches by session id; a plain `claude --resume` would leave Remote Control off.
if [ -n "$SID" ]; then CMD="claude remote-control --name $NAME --session-id $SID"; else CMD="claude remote-control --spawn=session --name $NAME"; fi
orca-ide terminal create --worktree "${ORCA_WORKTREE:-path:$ROOT}" --title "$NAME" --command "$CMD" --json
echo "created; inside the new terminal run /rename $NAME once Claude is up, then ensure_sessions.sh --list will see it."
