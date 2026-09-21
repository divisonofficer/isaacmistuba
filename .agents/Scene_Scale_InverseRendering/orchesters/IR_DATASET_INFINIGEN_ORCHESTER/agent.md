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
- Of the uncommitted Infinigen changes only ONE hunk is this session's: `vertex_count()` in
  `tools/infinigen/mesh_decimation.py`. The other 7 modified files (import_infinigen_scene.py,
  run_infinigen_import.sh, its test, infinigen_gen/_generate_indoors_safe/_modern_office_style/
  _wizard.py) and 6 untracked files (2 room tests, 3 cleanup tools, 1 dev_report html) are NOT
  this session's. Owner unknown; treat as a separate orphan.
- This session's earlier incarnation was `robomituba-d2`: the 09-07 and 09-09 reclaim records
  and the :8780 viewer server are its own work, not orphaned by a third party.
- Owns `apps/render_ir_principled_dataset_queue.py` storage_profile change + test_nir_passive fixtures
  (from one stash pop). Suite green at d77d7cc (175 passing) 2026-09-21.

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
- Confirmed by the session 2026-09-21: the server is its own. The +754 viewer diff and the
  storage_profile edit in apps/render_ir_principled_dataset_queue.py arrived together from one
  `git stash pop` (stash@{0} on 287d699 still exists and lists exactly those files). Authorship of
  the edits inside the stash is not determinable; the tree is holding them, nobody wrote them here.
- ASSIGNED: this session unbreaks the three `test_nir_passive.py` failures and owns the queue
  file's storage_profile change going forward (commit it once green, with the fixtures). Tell
  IR_DATASET_VIEWER_ORCHESTER (Codex) before touching anything under apps/ir_dataset_viewer/tests.
- Lesson recorded at its request: a pid mismatch proves a different process, not a different
  owner; check /proc/<pid>/environ CLAUDE_CODE_SESSION_ID before saying "not mine".

## Shared with OpticalNav
- `apps/import_infinigen_scene.py` and `apps/run_infinigen_import.sh` are also on the OpticalNav
  scene path (OPTICALNAV_NAVIGATION_ORCHESTER). Announce changes to that orchester before committing.

## Resources
- GPUs: none known. Claim through the pool lock and tell the director before any render.

## Does not
- Touch HSSD/ABO corpora or `modules/hssd_blender_ir`.
