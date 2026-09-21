---
# Sessions currently bound to this role file. Append a row when a new session
# (Claude peer, Codex, other) adopts the role; do not delete rows, mark them ended.
bound_sessions:
  - kind: claude-peer
    name: PC_OPTICALNAV_RENDER
    ref: 8b4294
    address: bridge:session_01Bt63UjmLJAY5KnNoLLFgru (Remote Control, Device 1)
    since: 2026-09-21
    status: active
codex_sessions: []      # e.g. - {id: <codex session id>, since: <date>, status: active}
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
---
# PC_OPTICALNAV_RENDER
- **Project:** OpticalNav

- **Session:** PC_OPTICALNAV_RENDER (Remote Control), **Device 1** (WSL2 + RTX 5090, OptiX 8) — not on Device 2
- **Tier:** worker (render driver)
- **Reports to:** OPTICALNAV_ORCHESTER for scene hand-off; director for status

## Remit
- Drive SV polar chain renders: sv1 base / perturbed / perturbed_active_polar, then sv2.
- Current: 20272904 perturbed_active_polar (ETA ~09:05Z 2026-09-21); next 20267404.
- Done: 20270704, 20273004, 20271804.

## Contract
- K=8 / tex=512 / freeze=1 / save_workers=1 / WORKER_START_TIMEOUT_S=300, single worker on GPU 0.
- No second daemon or driver on this host; no sync/render-scene while a render runs (OOM history).
