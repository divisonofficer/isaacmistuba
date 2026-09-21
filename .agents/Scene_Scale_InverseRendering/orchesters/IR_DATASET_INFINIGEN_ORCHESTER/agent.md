---
bound_sessions:
  - kind: claude-peer
    name: IR_DATASET_INFINIGEN_ORCHESTER
    ref: 2391414
    address: uds:/tmp/cc-socks/2391414.sock
    since: 2026-09-21
    status: active     # revived by the user 04:57Z from session 2e50bd36 (formerly listed as robomituba-a0)
codex_sessions: []
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
status: provisional — remit to be confirmed by the session's own reply
---
# IR_DATASET_INFINIGEN_ORCHESTER

- **Project:** Scene_Scale_InverseRendering (IR)
- **Tier:** orchester
- **Reports to:** PROJECT_DIRECTOR (DIRECTOR_MARK10 [c3cb4e])
- **Directs:** none yet; may request SONNET_WORKER_1/2 for read-only checks

## Remit (provisional)
- Infinigen-sourced IR corpora: `out/infinigen_single_room_*_rgb_active_nir_v2`, showcase and
  replan sets, and the Infinigen generation/import tooling (`scripts/infinigen_*.py`,
  `apps/import_infinigen_scene.py`, `tools/infinigen/`).
- Likely owner of the unclaimed uncommitted Infinigen script changes (8 files, +107/−8,
  mtime 2026-09-09) and 5 untracked test/cleanup tools. Confirm, then commit or drop them.

## Shared with OpticalNav
- `apps/import_infinigen_scene.py` and `apps/run_infinigen_import.sh` are also on the OpticalNav
  scene path (OPTICALNAV_NAVIGATION_ORCHESTER). Announce changes to that orchester before committing.

## Resources
- GPUs: none known. Claim through the pool lock and tell the director before any render.

## Does not
- Touch HSSD/ABO corpora or `modules/hssd_blender_ir`.
