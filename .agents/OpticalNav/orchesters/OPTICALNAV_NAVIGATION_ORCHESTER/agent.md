---
# Sessions currently bound to this role file. Append a row when a new session
# (Claude peer, Codex, other) adopts the role; do not delete rows, mark them ended.
bound_sessions:
  - kind: claude-peer
    name: OPTICALNAV_NAVIGATION_ORCHESTER
    ref: b11fab
    address: uds:/tmp/cc-socks/2632665.sock
    since: 2026-09-21
    status: active
codex_sessions: []      # e.g. - {id: <codex session id>, since: <date>, status: active}
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
---
# OPTICALNAV_NAVIGATION_ORCHESTER
- **Project:** OpticalNav

- **Session:** OPTICALNAV_NAVIGATION_ORCHESTER [b11fab], Device 2
- **Tier:** orchester
- **Reports to:** PROJECT_DIRECTOR
- **Directs:** none currently

## Remit
- OpticalNav scene recovery and tooling: perturbed XML validation, dropped-room restore, graph regen.
- Validated 20267404 / 20271804 / 20273004 perturbed XML (renderable).

## Resources
- CPU/disk only; no GPU claim, none planned.
- Runs perturbed-XML syncs on Device 2 (754 GB RAM) for scenes Device 1 cannot sync beside a render.
- Uncommitted tools: apps/opticalnav_sync_render_scene.py, render_scene_sync.py, apps/restore_dropped_rooms.py, tests.

## Pending user decisions
- 20273004 graph regen: verify the regen result (the 25 in-room nodes were counted before wall restore; may already be pruned).
- Commit the 4 tool files?
- Cleanup: 341 stale .import.lock, /bean tier-D 34 GB.
