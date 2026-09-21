# OpticalNav

Indoor navigation dataset: Infinigen scenes → viewpoint graph / grid / episodes →
grid × heading multimodal renders (Device 1) → export to gdrive:dataset/opticalnav.

| Agent | Owns | Machine |
|---|---|---|
| OPTICALNAV_ORCHESTER | pipeline, graph/episode compile, export + verify | Device 2 (daemon :8765; query for state) |
| OPTICALNAV_NAVIGATION_ORCHESTER | scene repair, perturbed XML, tooling | Device 2, CPU only |
| PC_OPTICALNAV_RENDER | SV polar render driver | Device 1, GPU 0 |
| PC_WORKER_1 | render queue management, user-assigned only | Device 1, daemon :8766 |

Workers: SONNET_WORKER_1 from `../shared_workers/` (readiness + daemon watch).

Scene flow: NAVIGATION_ORCHESTER validates → OPTICALNAV_ORCHESTER preps →
PC_OPTICALNAV_RENDER renders → OPTICALNAV_ORCHESTER exports.

Device rules:
- Device 1 has one GPU: one driver at a time.
- Device 1 cannot run a sync beside a render (11.9 GB WSL cap). Route perturbed-XML
  syncs to Device 2, which shares the scene tree over NFS, and never sync a scene
  Device 1 is currently rendering.
- Sync cost: without `render_scene_sync_gate.json`, `base_reusable` is false and the
  sync takes `full_rebuild` (~18 min, ~8k textures, no output for the first ~15 min —
  this is normal, not a failure loop). With the gate it takes `perturbation_only_rebuild`.
