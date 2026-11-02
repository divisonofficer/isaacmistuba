---
# Sessions currently bound to this role file. Append a row when a new session
# (Claude peer, Codex, other) adopts the role; do not delete rows, mark them ended.
bound_sessions:
  - kind: claude-peer
    name: OPTICALNAV_ORCHESTER
    ref: 25e773 (peer also reports robomituba-f2 [12385e])
    address: uds:/tmp/cc-socks/2629532.sock
    since: 2026-09-21
    status: active
codex_sessions: []      # e.g. - {id: <codex session id>, since: <date>, status: active}
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
---
# OPTICALNAV_ORCHESTER
- **Project:** OpticalNav

- **Session:** OPTICALNAV_ORCHESTER (ListAgents: robomituba-f2 [12385e]), Device 2
- **Tier:** orchester
- **Reports to:** PROJECT_DIRECTOR
- **Directs:** SONNET_WORKER_1 (export-readiness every 30 min, daemon health every 10 min)
- **Depends on:** PC_OPTICALNAV_RENDER / PC_WORKER_1 on Device 1 for renders

## Remit
- OpticalNav dataset pipeline: Infinigen scenes → graph/episode → export → gdrive:dataset/opticalnav.
- Prep = place graph (area-derived budget) → support build → 300 episodes → sv1/sv2 sweep
  → perturbation overlay → render-scene sync. Export = wizard --local (split+upload overlapped)
  → Drive md5/size verify → purge local bulk.
- 8 scenes exported and verified; 20267404 and 20272904 prepped, awaiting Device 1 renders.

## Resources
- Control-plane daemon pid 2679546 on :8765, configured GPU 0-3, queue empty, no CUDA context.
  Before any batch here: restart the daemon with ROBOMITUBA_RENDER_GPU_INDICES narrowed to
  devices nobody holds (0-3 collides with HSSD 0,2,3 and ABO 1), and warn the director.
- HARD RULE: no sync/render-scene on :8765 for a scene PC_OPTICALNAV_RENDER reports rendering;
  sync rewrites render_scene*.xml and mesh_cache that Device 1 reads.

## Reporting
- Reports to own user first; copies per-scene export verification to director.
