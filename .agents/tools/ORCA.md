# Orca registration for the fleet

Orca (`orca-ide`, app 1.4.205) only sees agents running inside Orca terminals. A session
started from VS Code or `claude remote-control` cannot be registered afterwards; it has to
be resumed inside an Orca terminal (`orca_adopt.sh NAME`, which refuses while the session is
still live elsewhere).

Fleet Run: `run_08a9cc052de7` (coordinator terminal = DIRECTOR_MARK10).

| Agent | Orca terminal handle | Host |
|---|---|---|
| DIRECTOR_MARK10 | term_ba01190f-6c2d-4466-8937-de69e62bc846 | Orca |
| IR_DATASET_INFINIGEN_ORCHESTER | term_eb71a360-90a0-44fa-abca-9c10170183b0 | Orca |
| SONNET_GPU_MANAGER | term_dd4ba567 (see `orca-ide terminal list`) | Orca |
| IR_DATASET_VIEWER_ORCHESTER (Codex) | term_9a444085-4438-4b38-b901-bd3cb58f840b | Orca |
| IR_PIPELINE_ORCHESTER | term_72a57721-430a (see `orca-ide terminal list`) | Orca (VS Code copy pid 2633842 still open) |
| HSSD, ABO, OPTICALNAV, NAVIGATION, SONNET_WORKER_1/2 | none yet | VS Code |

## Sending mail to an agent in an Orca terminal
```
orca-ide orchestration send --run run_08a9cc052de7 --to <terminal handle> \
  --type status --subject "<one line>" --body "<text>" --json
```
Terminal-handle mailboxes are not durable across terminal close. A recipient reads with
`orca-ide orchestration check --terminal <own handle> --json`; Claude sessions do not read
Orca mail on their own, so pair the first Orca message with a cross-session ping, or ask the
agent to check at its natural checkpoints.

## Migrating a VS Code session
1. Note its name is in `session_map.json` (`ensure_sessions.sh --list` harvests it).
2. Close the VS Code session (two processes on one transcript break peer addressing).
3. `bash .agents/tools/orca_adopt.sh NAME` → new Orca terminal running `claude --resume <id>`.
4. In that terminal run `/rename NAME`; refresh this table with the new handle.
