---
# Sessions currently bound to this role file. Append a row when a new session
# (Claude peer, Codex, other) adopts the role; do not delete rows, mark them ended.
bound_sessions:
  - kind: claude-peer
    name: IR_PIPELINE_ORCHESTER
    ref: 918f17
    address: uds:/tmp/cc-socks/2633842.sock
    since: 2026-09-21
    status: active
codex_sessions: []      # e.g. - {id: <codex session id>, since: <date>, status: active}
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
---
# IR_PIPELINE_ORCHESTER

- **Project:** Scene_Scale_InverseRendering (IR)
- **Session:** IR_PIPELINE_ORCHESTER [918f17] (lock row robomituba-12), Device 2
- **Tier:** orchester (lead for the IR project's model side)
- **Reports to:** PROJECT_DIRECTOR
- **Directs:** SONNET_WORKER_1 (v13 liveness, root disk, codebase-memory stage leak)

## Remit
- Own memory-IR v13 training (volume pose-query PBR, worktree scene_ir_ff_v13) and its evals.
- Decide corpus mix; consumes HSSD render_hover_v1 (.done scenes) and ABO corpora.
- Current: epoch 7/20 on GPUs 4,5,7 (bf16 held-out eval finished; GPU 5 back to training only).
- Consumes: HSSD render_hover_v1 (42 pinned .done scenes) and abo_cornell_video_v1 (manifest v3),
  plus an ABO set it recorded as "abo_cornell_v1", which does not exist on disk; confirm the path the
  run actually read (probably abo_cornell_v2) and correct the name in the manifests.
- Not yet consumed: abo_cornell_env_v1 (/bean/ir_dataset/abo_cornell_env_v1, 50 scenes, ~3,400 frames
  when done). New data, no overlap with abo_cornell_video_v1; frame-id prefixes differ
  (hssd_abo_env_ vs hssd_abo_cornell_) so both merge into one index. Discriminate on manifest key
  `environment_type`, not composer_version (unchanged on purpose).
- Manifests v3 pinned to 42 done HSSD scenes until HSSD orchester reports completion.

## Resources
- GPUs 4,5,7 — claimed at run start, no widening (user's call 2026-09-16).

## Milestones
- 2026-09-21 v13 ep6 held-out, novel-pose query: albedo 0.060 / normal 25.0° / pointmap 0.43 m
  (v10: 0.072 / 32.0° / 1.74 m). Seen-pose albedo 0.038 vs as-image bound 0.033.

- 2026-09-21 query-gap diagnosis (scene_ir_ff/dev_report/2026-09-21-memory-ir-query-diagnosis):
  gap is neither depth selection nor missing information; tokens decode only on their source
  patch grid. Decision (user): B, memory-only pose query (true NVS); warp_pred kept as upper-bound
  control (albedo 0.039 / normal 18.9°). v14 branch memory-ir-v14, worktree scene_ir_ff_v14,
  arms a (decoder) → b (+memory adapter) → c (+distill + depth supervision), ~3 epochs each from
  v13 ep6. Blocked on GPUs until v13 ends (~18 h) or the user swaps. Director reviewed, no objection.

## Reporting
- Epoch milestones and eval results to director; failures immediately.

## Does not
- Edit modules/hssd_blender_ir or ABO render trees.
