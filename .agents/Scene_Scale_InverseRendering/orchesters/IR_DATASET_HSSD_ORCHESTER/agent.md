---
# Sessions currently bound to this role file. Append a row when a new session
# (Claude peer, Codex, other) adopts the role; do not delete rows, mark them ended.
bound_sessions:
  - kind: claude-peer
    name: IR_DATASET_HSSD_ORCHESTER
    ref: 13b544
    address: uds:/tmp/cc-socks/2631136.sock
    since: 2026-09-21
    status: active
codex_sessions: []      # e.g. - {id: <codex session id>, since: <date>, status: active}
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
---
# IR_DATASET_HSSD_ORCHESTER
- **Project:** Scene_Scale_InverseRendering (IR)

- **Session:** IR_DATASET_HSSD_ORCHESTER [13b544], Device 2
- **Tier:** orchester
- **Reports to:** PROJECT_DIRECTOR
- **Directs:** SONNET_WORKER_1 (completion count, tree sha256, worker liveness, FAIL count, 6h heartbeat);
  SONNET_WORKER_2 (manifest vs disk, 28-channel completeness, dup frame ids, take counts)

## Remit
- Own HSSD hover video corpus render_hover_v1: 100 scenes, 15 takes where the geometry
  supplies them. Five scenes top out lower by design (102343992:10, 102344115:11,
  102816600:9, 104348394:13, 105515430:14) and must not be re-rendered for the shortfall.
- Edits in worktree modules/hssd_blender_ir_bd (branch work/hover-bd); reads the shared
  modules/hssd_blender_ir checkout, does not write it (sole writer: ABO orchester, stopped at e3cf4a9).

## Resources
- GPUs 0,2,3, three queue loops. Lock row renamed to IR_DATASET_HSSD_ORCHESTER 2026-09-21.
- Reads v3 blends (~98 GB) — deletion waits for corpus completion and user approval.

## Commitments
- Notify IR_PIPELINE_ORCHESTER before any .done is removed; one line when corpus completes.
- Workers must not touch .done/.coat/.claim.

## Reporting
- Scene count every 6h via worker heartbeat; failures immediately.
- Silence is the failure signal: check the heartbeat's age before quoting its numbers;
  past ~7h report "watch unverified" instead of stale figures.
