#!/usr/bin/env bash
# ensure_sessions.sh — keep every non-PC fleet agent alive under Remote Control.
#
# For each agent name in the roster (every agent.md under .agents/ except
# OpticalNav/workers/PC_*), check the Claude Code session registry
# (~/.claude/sessions/<pid>.json). If no live process carries that name,
# start `claude remote-control --name <NAME>` in a detached tmux session,
# reattaching to the agent's last session id when one is known so the
# conversation context survives.
#
# Usage: ensure_sessions.sh [--dry-run] [--once NAME] [--list]
# Env:   FLEET_ROOT (default /jarvis/project/robomituba)
#        FLEET_SESSION_MAP (default $FLEET_ROOT/.agents/tools/session_map.json)
set -euo pipefail

FLEET_ROOT="${FLEET_ROOT:-/jarvis/project/robomituba}"
AGENTS_DIR="$FLEET_ROOT/.agents"
MAP="${FLEET_SESSION_MAP:-$AGENTS_DIR/tools/session_map.json}"
REG="$HOME/.claude/sessions"
DRY=0; ONLY=""; LIST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --once) ONLY="$2"; shift ;;
    --list) LIST=1 ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac; shift
done
command -v tmux >/dev/null || { echo "tmux required" >&2; exit 1; }
command -v claude >/dev/null || { echo "claude CLI not on PATH" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 required" >&2; exit 1; }
[ -f "$MAP" ] || echo '{}' > "$MAP"

# Roster: one line "SESSION_NAME" per agent.md, excluding PC_* (Device 1, not this
# host) and files whose frontmatter says `ensure_session: false` (e.g. Codex roles).
# `claude_session_name:` in the frontmatter overrides the folder name.
roster() {
  python3 - "$AGENTS_DIR" <<'PY'
import os, re, sys
root = sys.argv[1]
out = set()
for dp, dn, fn in os.walk(root):
    if "agent.md" not in fn: continue
    folder = os.path.basename(dp)
    if folder.startswith("PC_"): continue
    txt = open(os.path.join(dp, "agent.md")).read()
    fm = ""
    if txt.startswith("---\n"):
        end = txt.find("\n---", 4)
        fm = txt[4:end] if end > 0 else ""
    if re.search(r"^ensure_session:\s*false", fm, re.M): continue
    m = re.search(r"^claude_session_name:\s*([A-Za-z0-9_.-]+)", fm, re.M)
    out.add(m.group(1) if m else folder)
print("\n".join(sorted(out)))
PY
}

# live_pid NAME -> pid of a running session registered under that name, or empty.
live_pid() {
  local name="$1"
  python3 - "$REG" "$name" <<'PY'
import json, os, sys, glob
reg, name = sys.argv[1], sys.argv[2]
for f in glob.glob(os.path.join(reg, "*.json")):
    try: d = json.load(open(f))
    except Exception: continue
    # Match by peer name, or by the tmux session this script created: `--name`
    # sets the Remote Control environment name, while the peer name stays
    # derived (robomituba-XX) until the session renames itself.
    tm = str(d.get("tmux") or "")
    if d.get("name") != name and not tm.startswith(f"agent_{name}:"): continue
    pid = d.get("pid")
    try: os.kill(pid, 0)
    except Exception: continue
    sock = d.get("messagingSocketPath")
    if sock and not os.path.exists(sock): continue
    print(pid); break
PY
}

# remember NAME -> record the live session's id in the map for later reattach.
remember() {
  local name="$1"
  python3 - "$REG" "$MAP" "$name" <<'PY'
import json, os, sys, glob, time
reg, mp, name = sys.argv[1:4]
m = json.load(open(mp))
for f in glob.glob(os.path.join(reg, "*.json")):
    try: d = json.load(open(f))
    except Exception: continue
    tm = str(d.get("tmux") or "")
    if (d.get("name") == name or tm.startswith(f"agent_{name}:")) and d.get("sessionId"):
        m[name] = {"sessionId": d["sessionId"], "bridgeSessionId": d.get("bridgeSessionId"),
                   "seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        json.dump(m, open(mp, "w"), indent=2, sort_keys=True); break
PY
}

known_session_id() {
  python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m.get(sys.argv[2],{}).get("sessionId",""))' "$MAP" "$1"
}

launch() {
  local name="$1" sid tmux_name cmd
  sid="$(known_session_id "$name")"
  tmux_name="agent_${name}"
  cmd="cd $FLEET_ROOT && claude remote-control --spawn=session --name $name"
  [ -n "$sid" ] && cmd="$cmd --session-id $sid"
  # If reattach by id is refused (expired, moved), fall back to a fresh session.
  cmd="$cmd || (echo 'reattach failed, starting fresh' && cd $FLEET_ROOT && claude remote-control --spawn=session --name $name)"
  if tmux has-session -t "$tmux_name" 2>/dev/null; then
    echo "  tmux $tmux_name exists but no live session registered; leaving it (inspect manually)"
    return
  fi
  if [ "$DRY" = 1 ]; then echo "  would run: tmux new-session -d -s $tmux_name \"$cmd\""; return; fi
  tmux new-session -d -s "$tmux_name" "$cmd"
  echo "  started tmux $tmux_name${sid:+ (reattach $sid)}"
  echo "  note: peer name will be derived (robomituba-XX) until the session runs /rename $name"
}

for name in $(roster); do
  [ -n "$ONLY" ] && [ "$name" != "$ONLY" ] && continue
  pid="$(live_pid "$name")"
  if [ -n "$pid" ]; then
    remember "$name"
    [ "$LIST" = 1 ] && echo "$name: live pid $pid"
    continue
  fi
  echo "$name: DOWN"
  [ "$LIST" = 1 ] && continue
  launch "$name"
done
