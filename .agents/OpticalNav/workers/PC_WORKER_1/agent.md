---
# Sessions currently bound to this role file. Append a row when a new session
# (Claude peer, Codex, other) adopts the role; do not delete rows, mark them ended.
bound_sessions:
  - kind: claude-peer
    name: PC_WORKER_1
    ref: 93a7a7
    address: bridge:session_013wz3zwua74ubWs7acvRtW1 (Remote Control, Device 1)
    since: 2026-09-21
    status: active
codex_sessions: []      # e.g. - {id: <codex session id>, since: <date>, status: active}
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
---
# PC_WORKER_1
- **Project:** OpticalNav

- **Session:** PC_WORKER_1 (Remote Control), **Device 1** (WSL2 + RTX 5090) — not on Device 2
- **Tier:** worker
- **Reports to:** the user directly; director receives status only
- **Takes assignments from:** the user only (declines peer-assigned tasks by its own rules)

## Remit
- Manage OpticalNav SV1/SV2 polar render queues for Infinigen apartment scenes.
- Queue of 10 scenes (~214k views) complete and verified; currently free.

## Resources
- Own daemon on :8766. Device 1 has one GPU; never start a second driver while PC_OPTICALNAV_RENDER's scene is in flight.
