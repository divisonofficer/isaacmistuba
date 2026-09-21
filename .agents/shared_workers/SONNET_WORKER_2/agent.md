---
# Sessions currently bound to this role file. Append a row when a new session
# (Claude peer, Codex, other) adopts the role; do not delete rows, mark them ended.
bound_sessions:
  - kind: claude-peer
    name: SONNET_WORKER_2
    ref: e18be3
    address: uds:/tmp/cc-socks/2628313.sock
    since: 2026-09-21
    status: active
codex_sessions: []      # e.g. - {id: <codex session id>, since: <date>, status: active}
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
---
# SONNET_WORKER_2
- **Project:** shared pool (serves both OpticalNav and IR)

- **Session:** SONNET_WORKER_2 [e18be3], Device 2
- **Tier:** worker (read-only verification)
- **Reports to:** IR_DATASET_ABO_ORCHESTER, IR_DATASET_HSSD_ORCHESTER; director for capacity

## Remit
- ABO corpus: verification sweep done (38 scenes, 2580 frames, 0 problems); stall watch every 5 min until outdoor_street 38-49 completes.
- HSSD .done corpus (49 scenes): sweep running; re-run at corpus completion.
- Scripts live in session scratchpad, not the repo.

## Tooling
- ponytail, codebase-memory-mcp: allowed.
- headroom: allowed in trial mode under the README's conditions (learn off, no repo writes,
  localhost proxy, one-week report to the director).

## Does not
- Edit files, kill processes, or touch .done/.coat/.claim.
