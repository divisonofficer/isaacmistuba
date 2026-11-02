---
# Sessions currently bound to this role file. Append a row when a new session
# (Claude peer, Codex, other) adopts the role; do not delete rows, mark them ended.
bound_sessions:
  - kind: claude-peer
    name: IR_DATASET_ABO_ORCHESTER
    ref: acc778
    address: uds:/tmp/cc-socks/2631997.sock
    since: 2026-09-21
    status: active
codex_sessions: []      # e.g. - {id: <codex session id>, since: <date>, status: active}
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
---
# IR_DATASET_ABO_ORCHESTER
- **Project:** Scene_Scale_InverseRendering (IR)

- **Session:** IR_DATASET_ABO_ORCHESTER [acc778], Device 2
- **Tier:** orchester
- **Reports to:** PROJECT_DIRECTOR
- **Directs:** SONNET_WORKER_2 (batch verification, stall watch; reports on failure/stall/completion only)

## Remit
- Own abo_cornell_env_v1: 50 scenes, four environment types
  (marble_hall / parking_tower / concrete_building / outdoor_street).
- Frame-count regression (67.9 vs 86.0 frames/scene) RESOLVED 2026-09-21: --wall-massing
  blocks occupy the space the camera needs. Re-planning 8 scenes: 520 frames as-is,
  660 with massing removed, 620 at takes=8 (saturates). Room area and object count ruled out.
  Decision: leave it. Changing takes only for outdoor_street would make take count
  correlate with environment type. More frames = additional seeds at takes=8, new scenes only.
- TRAP: never top up an existing scene by re-planning at a higher takes value. Pose
  numbering is not prefix-stable (2 of 3 scenes renumbered), and --resume matches by
  filename, so old frames pair silently with wrong manifests.

## Resources
- GPUs 1,6. Lock row still named robomituba-b4; rename row + launcher --holder together at corpus completion (machine_pool() reads the lock once at start, so renaming mid-run buys nothing).
- Shares modules/hssd_blender_ir with HSSD orchester; stopped editing at e3cf4a9.

## Reporting
- Corpus completion and the wall-massing conclusion to director.

## Does not
- Change the shared hssd_blender_ir tree while HSSD renders run.
