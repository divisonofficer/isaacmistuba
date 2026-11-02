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
- GPUs 4,5,7 — claimed at run start, no widening (user's call 2026-09-16). Swapped v13→v14a 2026-09-21 by the user.

## Milestones
- 2026-09-21 v13 ep6 held-out, novel-pose query: albedo 0.060 / normal 25.0° / pointmap 0.43 m
  (v10: 0.072 / 32.0° / 1.74 m). Seen-pose albedo 0.038 vs as-image bound 0.033.

- 2026-09-21 query-gap diagnosis (scene_ir_ff/dev_report/2026-09-21-memory-ir-query-diagnosis):
  gap is neither depth selection nor missing information; tokens decode only on their source
  patch grid. Decision (user): B, memory-only pose query (true NVS); warp_pred kept as upper-bound
  control (albedo 0.039 / normal 18.9°). v14 branch memory-ir-v14, worktree scene_ir_ff_v14,
  arms a (decoder) → b (+memory adapter) → c (+distill + depth supervision), ~3 epochs each from
  v13 ep6. Blocked on GPUs until v13 ends (~18 h) or the user swaps. Director reviewed, no objection.

- 2026-09-21 v14a ep2 (10 volume samples, 8 views): query roughness 0.045 / normal 0.155 / depth 0.065
  vs v13 ep7 0.048 / 0.159 / 0.086; albedo 0.055 vs 0.051 (high-frequency albedo lives in the image
  residual the pose query cannot see). Pre-registered arm-a check armed on the 40 diag samples.
- Sent RESEARCHER a full state brief by Orca (msg_0a49f74cc745).

- 2026-09-23: v14a missed gate at ep7 under changed conditions (not a decoder verdict); v14b flat, stopped;
  v14c unrun. v15 = TokenUnpack (sub-patch shift control), v16 = v15 + AppearanceMemory (input ResNeXt
  pyramids stored at observation, read via query's predicted depth into the albedo residual port).
  v16 ep15 ablation (gates zeroed, same weights, 40 views): albedo 0.0516 vs 0.0562, t=−3.44; other
  channels unchanged. v13→v16: only normal significantly better (−2.5°). Holds 4,5,7; declines widening.

- 2026-09-23 GPUs: v18a on 4, v18b on 5, 7 idle reserved for v18c. No-widening rule is the binding
  constraint; an arbiter allocates but cannot consent for its user.
- RESEARCHER review, as acted on (delivered as Orca message, not a file): decoded-map warp beats token
  warp on normal too (18.9° vs 23.0°) so the "albedo has an image bypass" claim was dropped and the
  readout-bottleneck thesis strengthened; GT-depth result narrowed to "sampling interventions tried
  move little"; arm b no longer called a decisive store-vs-read test; arms branched from one checkpoint.

## Reporting
- Epoch milestones and eval results to director; failures immediately.

## Does not
- Edit modules/hssd_blender_ir or ABO render trees.
