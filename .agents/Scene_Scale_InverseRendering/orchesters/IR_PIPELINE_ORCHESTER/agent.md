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
- Consumes: HSSD render_hover_v1 (42 pinned .done scenes), abo_cornell_v1, abo_cornell_video_v1
  (manifest v3). abo_cornell_env_v1 (ABO orchester's current 50-scene corpus) not yet consumed;
  name relation being confirmed with ABO orchester.
- Manifests v3 pinned to 42 done HSSD scenes until HSSD orchester reports completion.

## Resources
- GPUs 4,5,7 — claimed at run start, no widening (user's call 2026-09-16).

## Milestones
- 2026-09-21 v13 ep6 held-out, novel-pose query: albedo 0.060 / normal 25.0° / pointmap 0.43 m
  (v10: 0.072 / 32.0° / 1.74 m). Seen-pose albedo 0.038 vs as-image bound 0.033.

## Reporting
- Epoch milestones and eval results to director; failures immediately.

## Does not
- Edit modules/hssd_blender_ir or ABO render trees.
