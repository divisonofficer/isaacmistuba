#!/usr/bin/env bash
# Spawn RESEARCHER (Codex, gpt-6-astra) in an Orca terminal. Run from any shell on Device 2.
# Codex's bwrap sandbox cannot pivot_root in this container, so it runs with the sandbox
# bypassed, the same way the user's other Codex terminals run here.
set -euo pipefail
ROOT=/jarvis/project/robomituba
PROMPT='You are RESEARCHER in the robomituba fleet. Read /jarvis/project/robomituba/.agents/research/RESEARCHER/agent.md first and follow its directive 1.'
orca-ide terminal create --worktree "path:$ROOT" --title RESEARCHER --focus \
  --command "cd $ROOT && codex --dangerously-bypass-approvals-and-sandbox -m ${CODEX_MODEL:-gpt-6-astra} \"$PROMPT\"" --json
