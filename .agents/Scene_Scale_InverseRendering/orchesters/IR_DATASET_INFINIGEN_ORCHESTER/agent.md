---
bound_sessions:
  - kind: claude-peer
    name: IR_DATASET_INFINIGEN_ORCHESTER
    ref: 2391414
    address: uds:/tmp/cc-socks/2391414.sock
    since: 2026-09-21
    status: active     # revived by the user 04:57Z from session 2e50bd36; earlier peer names of this
                       # same transcript: robomituba-d2 → robomituba-ed → robomituba-6d → robomituba-a0.
                       # /bean reclaim records signed robomituba-d2 / -ed are this session's.
codex_sessions: []
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
status: adopted (remit confirmed by the session 2026-09-21 05:05Z)
---
# IR_DATASET_INFINIGEN_ORCHESTER

- **Project:** Scene_Scale_InverseRendering (IR)
- **Tier:** orchester
- **Reports to:** PROJECT_DIRECTOR (DIRECTOR_MARK10 [c3cb4e])
- **Directs:** none yet; may request SONNET_WORKER_1/2 for read-only checks

## Remit (confirmed)
- The Infinigen-sourced IR corpus end to end: generation, import, Stage-1/2, render, review tooling.
  Not HSSD, not ABO, not v13 training. Reuses `hover_path.py` arithmetic from hssd_blender_ir, never edits it.
- Uncommitted Infinigen script changes (8 files, +107/−8, mtime 2026-09-09) and 5 untracked
  test/cleanup tools: ownership still to be stated file by file (asked in roll-call).

## Known facts
- Work-room placement programmes (office, meeting, break room, restroom, warehouse) never ran before
  commits adfbbe3 / b2f7d4f / d185950: an early-return guard skipped exactly those room types, so
  existing corpora with those rooms were furnished by Infinigen's home constraints (no desk/chair/monitor).
  Any consumer comparing old and new Infinigen scenes must account for this.
- In flight: apartment hover takes via `apps/build_apartment_hover_poses.py` (13 apartments, 161 rooms,
  3 takes/room), free-pose format, no renderer change. Not rendered; all 8 GPUs claimed.

## Pending user decisions (recorded in /bean/ir_dataset_work/.control/)
- 62 superseded dataset versions across 41 scenes: delete?
- 229 GB duplicated between /bean/ir_dataset and /bean/ir_dataset_work. NOT a clean duplicate: the
  work copy holds 20.9 GB of passive NIR the published copy lacks. Deleting on name+fingerprint match
  would destroy a channel. Turns on whether a published dataset is a fixed snapshot or a live copy.

## Attribution established from artifacts (2026-09-21)
- The :8780 viewer backend, pid 2997224, was started by THIS transcript on 2026-09-06 04:38:24
  (/proc environ CLAUDE_CODE_SESSION_ID=2e50bd36…, log /bean/ir_dataset_work/controller_backend.log).
  This session owns that process; its restart is coordinated with IR_DATASET_VIEWER_ORCHESTER.
- The same window edited backend/controller.py via heredocs and ran `git stash pop`; the
  storage_profile change in apps/render_ir_principled_dataset_queue.py was dirty and known at the
  restart. Awaiting this session's transcript check on (a) storage_profile authorship, (b) whether
  the stash pop restored the +754 viewer diff.

## Shared with OpticalNav
- `apps/import_infinigen_scene.py` and `apps/run_infinigen_import.sh` are also on the OpticalNav
  scene path (OPTICALNAV_NAVIGATION_ORCHESTER). Announce changes to that orchester before committing.

## Resources
- GPUs: none known. Claim through the pool lock and tell the director before any render.

## Does not
- Touch HSSD/ABO corpora or `modules/hssd_blender_ir`.
