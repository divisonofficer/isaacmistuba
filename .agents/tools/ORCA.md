# Orca registration for the fleet

Orca (`orca-ide`, app 1.4.205) only sees agents running inside Orca terminals. A session
started from VS Code or `claude remote-control` cannot be registered afterwards; it has to
be resumed inside an Orca terminal (`orca_adopt.sh NAME`, which refuses while the session is
still live elsewhere).

Fleet Run: `run_08a9cc052de7` (coordinator terminal = DIRECTOR_MARK10).

| Agent | Orca terminal handle | Host |
|---|---|---|
| DIRECTOR_MARK10 | term_ba01190f-6c2d-4466-8937-de69e62bc846 | Orca (coordinator) |
| IR_PIPELINE_ORCHESTER | term_d6eb0800-0fe9-4163-ba44-91421ba0c587 | Orca, worktree IR_DATASET |
| IR_DATASET_HSSD_ORCHESTER | term_82ca3029-bca9-4e41-b326-7216900c840d | Orca, worktree IR_DATASET |
| IR_DATASET_ABO_ORCHESTER | term_af8f3d31-3796-432e-926e-241cf6cd7c78 | Orca, worktree IR_DATASET |
| IR_DATASET_INFINIGEN_ORCHESTER | term_b42cf680-1b29-4175-9cf0-f0c4976df0a3 | Orca, worktree IR_DATASET |
| IR_DATASET_VIEWER_ORCHESTER (Codex) | term_9a444085-4438-4b38-b901-bd3cb58f840b | Orca |
| OPTICALNAV_ORCHESTER | term_538be2b3-8f43-4c7e-b256-daaeda1f01ed | Orca, worktree OpticalNav |
| OPTICALNAV_NAVIGATION_ORCHESTER | term_38731d3a-1277-4474-ace8-c07f9b5759e7 | Orca, worktree OpticalNav |
| SONNET_WORKER_1 | term_f71b4ccd-fb32-48ff-b139-7c4bc0cd72d8 | Orca |
| SONNET_WORKER_2 | term_edb95088-642f-4b9f-bb99-a94d6c5cff8b | Orca |
| SONNET_GPU_MANAGER | term_dd4ba567-79a7-4168-b75f-0735c0293e9b | Orca |
| RESEARCHER (Codex gpt-6-astra) | term_65853e59-37d5-463e-bcde-b3cdb18d840b | Orca |
| PC_OPTICALNAV_RENDER, PC_WORKER_1 | none | Device 1, Remote Control only |

All VS Code copies were closed 2026-09-21 05:30Z; every local agent now runs in an Orca
terminal resumed from its previous session id, so context carried over.

## Worktrees
Orca has three worktree entries on the same checkout: `robomituba` (root), `IR_DATASET`, and
`OpticalNav`. The four IR Claude orchesters sit in `IR_DATASET` (moved 06:20Z); the two OpticalNav orchesters
in `OpticalNav` (06:10Z); director, shared workers, RESEARCHER and the Codex viewer thread in root. A terminal
cannot be moved between worktrees: close it and recreate with
`ORCA_WORKTREE=name:OpticalNav bash .agents/tools/orca_adopt.sh NAME` (resumes by local uuid; `claude remote-control --session-id` needs a bridge id and fails on a local uuid).

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
