# Orca registration for the fleet

Orca (`orca-ide`, app 1.4.205) only sees agents running inside Orca terminals. A session
started from VS Code or `claude remote-control` cannot be registered afterwards; it has to
be resumed inside an Orca terminal (`orca_adopt.sh NAME`, which refuses while the session is
still live elsewhere).

Fleet Run: `run_08a9cc052de7` (coordinator terminal = DIRECTOR_MARK10).

| Agent | Orca terminal handle | Host |
|---|---|---|
| DIRECTOR_MARK10 | term_818fc3ac-4656 (see `orca-ide terminal list`) | Orca root (coordinator) |
| IR_PIPELINE_ORCHESTER | term_b2aa0c6a-43c4-4c56-9a7c-2928f7dcf357 | Orca, worktree IR_DATASET |
| IR_DATASET_HSSD_ORCHESTER | term_20d69106-269d-4652-b822-f7198018ee64 | Orca, worktree "HSSD dataset" |
| IR_DATASET_ABO_ORCHESTER | term_be07d349-f279-4cb5-a774-1d4b9137bb8b | Orca, worktree IR_DATASET_ABO |
| IR_DATASET_INFINIGEN_ORCHESTER | term_653a4bff-0b38-4bf7-b76b-fd50ccf99a17 | Orca, worktree IR_Dataset_Infinigen |
| OPTICALNAV_ORCHESTER | term_9361d703-bb2b-4996-aa8a-04638bf6b769 | Orca, worktree OpticalNav |
| OPTICALNAV_NAVIGATION_ORCHESTER | term_32d153e9-49e2-40f2-b76f-16664a2f0977 | Orca, worktree OpticalNav |
| SONNET_WORKER_1 | term_3d5d0540-be64-4e6d-9b6e-2e0b0dc52827 | Orca, worktree Workers |
| SONNET_WORKER_2 | term_77d064f0-bbee-460a-a563-c1191742492b | Orca, worktree Workers |
| SONNET_GPU_MANAGER | term_99e833bb-d9ed-4b52-ae3a-e4fbe30af74f | Orca, worktree Workers |
| Codex threads (viewer, RESEARCHER, Infinigen worker) | gone with the server restart; respawn via their role files | — |
| PC_OPTICALNAV_RENDER, PC_WORKER_1 | none | Device 1, Remote Control only |

Fleet revived 2026-09-30 04:40Z after the Orca server restart (all nine resumed from
session_map ids into their worktrees). The fleet Run id run_08a9cc052de7 predates the restart;
check `orca-ide orchestration run-list` before relying on it.

## Worktrees
Orca worktree entries on the same checkout: `robomituba` (root), `IR_DATASET`, `IR_DATASET_ABO`,
`HSSD dataset`, `IR_Dataset_Infinigen`, `OpticalNav`, and `Workers`. The four IR Claude orchesters sit in `IR_DATASET` (moved 06:20Z); the two OpticalNav orchesters
in `OpticalNav` (06:10Z); the two Sonnet workers and the GPU manager in `Workers` (06:50Z);
director, RESEARCHER and the Codex viewer thread in root. A terminal
cannot be moved between worktrees: close it and recreate with
`ORCA_WORKTREE=name:OpticalNav bash .agents/tools/orca_adopt.sh NAME` (resumes by local uuid; `claude remote-control --session-id` needs a bridge id and fails on a local uuid).

## Sending mail to an agent in an Orca terminal
```
orca-ide orchestration send --run run_08a9cc052de7 --to <terminal handle> \
  --type status --subject "<one line>" --body "<text>" --json
```
Terminal-handle mailboxes are not durable across terminal close, and an empty mailbox reads
exactly like a dead one; confirmed bidirectional 2026-09-21 06:40Z (DIRECTOR ↔ INFINIGEN). A recipient reads with
`orca-ide orchestration check --terminal <own handle> --json`; Claude sessions do not read
Orca mail on their own, so pair the first Orca message with a cross-session ping, or ask the
agent to check at its natural checkpoints.

## Migrating a VS Code session
1. Note its name is in `session_map.json` (`ensure_sessions.sh --list` harvests it).
2. Close the VS Code session (two processes on one transcript break peer addressing).
3. `bash .agents/tools/orca_adopt.sh NAME` → new Orca terminal running `claude --resume <id>`.
4. In that terminal run `/rename NAME`; refresh this table with the new handle.
