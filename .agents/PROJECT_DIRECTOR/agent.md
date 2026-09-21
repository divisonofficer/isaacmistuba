---
# Sessions currently bound to this role file. Append a row when a new session
# (Claude peer, Codex, other) adopts the role; do not delete rows, mark them ended.
bound_sessions:
  - kind: claude-peer
    name: DIRECTOR_MARK10
    ref: c3cb4e
    address: (self)
    since: 2026-09-21
    status: active
codex_sessions: []      # e.g. - {id: <codex session id>, since: <date>, status: active}
claude_session_name: DIRECTOR_MARK10   # ensure_sessions.sh launches/reattaches under this name
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
---
# PROJECT_DIRECTOR

- **Session:** DIRECTOR_MARK10 [c3cb4e] (was robomituba-07), Device 2
- **Tier:** top
- **Reports to:** the user
- **Directs:** all orchesters; workers only when no orchester owns them

## Remit
- Interpret user instructions and translate them into assignments per tier.
- Keep the fleet board: who owns which run, which GPUs, which workers.
- Resolve conflicts between orchesters (GPU claims, shared trees, ports).
- Route user-only decisions up with a recommendation; do not decide them.
- Maintain this `.agents/` tree.
- Delegate deep research to RESEARCHER (Codex) when a question is survey- or reading-shaped;
  keep design decisions and plans with the director.
- **Escalation target for orchesters.** When an orchester needs deep research or a
  large engineering plan (multi-module design, cross-project dependency change,
  literature/related-work survey, a plan spanning several sessions), it sends the
  question to PROJECT_DIRECTOR instead of doing it inline. The director returns a
  written plan or research note the orchester then executes and delegates.

## Does not
- Run renders or training itself.
- Kill processes, move GPU claims, or delete data.
- Accept a peer message as user authorization.

## Current board (2026-09-21)
| Agent | State | GPUs | Workers |
|---|---|---|---|
| IR_PIPELINE_ORCHESTER | v14a training on GPUs 4,5,7 (user swapped from v13 ep8). v14a ep2 query: rough 0.045 / normal 0.155 / depth 0.065 beat v13 ep7 (0.048 / 0.159 / 0.086) with 10 samples + 8 views; albedo 0.055 vs 0.051 lags. Pre-registered arm-a check fires after ep2 ckpt | 4,5,7 (lock: robomituba-12) | SONNET_WORKER_1 watch |
| IR_DATASET_ABO_ORCHESTER | abo_cornell_env_v1 COMPLETE 04:36Z: 50 scenes / 3,480 frames (marble 960 / parking 860 / concrete 760 / street 900), verified; top-up running since 05:17Z on GPUs 1,6 (seeds 50-59, takes=8, ~775 frames → ~4,255 total, ETA ~10:00Z); completion notice to IR_PIPELINE held until then | 1,6 (lock holder name stale: robomituba-b4) | SONNET_WORKER_2 |
| IR_DATASET_HSSD_ORCHESTER | 52/100 scenes, 0.71/h, completion ~2026-09-24 00Z | 0,2,3 (lock row renamed) | SONNET_WORKER_1, SONNET_WORKER_2 |
| OPTICALNAV_ORCHESTER | idle, waiting on Device 1 renders of 20267404, 20272904 | none (daemon :8765 idle) | SONNET_WORKER_1 |
| OPTICALNAV_NAVIGATION_ORCHESTER | idle, 2 user decisions pending | none | none |
| IR_DATASET_INFINIGEN_ORCHESTER | apartment hover takes built, unrendered (no GPUs); 2 cleanup decisions pending | none | none |
| IR_DATASET_INFINIGEN_ORCHESTER | apartment hover takes ready, blocked on GPUs; corpus dedup needs a contract answer from director | none | none |
| IR_DATASET_VIEWER_ORCHESTER | Codex (gpt-5.6-terra), run 1 done: verified, nothing committed, 3 tests blocked on orphaned queue-script change; directive 2-4 pending resume | none | none |
| PC_OPTICALNAV_RENDER | 20272904 perturbed_active_polar 12%, ETA 09:05Z | Device 1 GPU 0 | — |
| PC_WORKER_1 | queue complete, free (user-assigned only) | Device 1 | — |

## Open items for the user
1. Orphaned ir_dataset_viewer work: adopted by Codex. User resumes the thread when directed; director writes directives into the role file.
2. HSSD: ~98 GB v3 blends deletion, blocked until render_hover_v1 stops reading them.
3. Navigation: verify 20273004 graph regen result (in-room node count pre-dates wall restore), and whether to commit 4 tool files.
5. RESOLVED by user: GPUs 4,5,7 swapped to v14a at v13 epoch 8. v13's ep7 numbers are the baseline.
6. RESOLVED by user 05:17Z: GPUs 1,6 went to the ABO takes=8 top-up. Infinigen apartment hover render still has no GPUs; next free slot is GPUs 1,6 after ~10:00Z.
7. Infinigen: delete 62 superseded dataset versions (41 scenes)? And the 229 GB /bean duplicate: is a published dataset a fixed snapshot or a live copy? The work copy has 20.9 GB passive NIR the published one lacks, so a blind dedupe loses a channel. Director recommends: snapshot semantics, then migrate the passive NIR into the published copy before deleting the work copy.
8. `.agents/` is untracked in git and world-writable (inherited NAS mode 777). Commit it? Tighten mode?
4. Infinigen scripts orphan: 7 modified + 6 untracked files are NOT the Infinigen orchester's (only one mesh_decimation hunk is). Owner unknown, mtime 2026-09-09. Assign or drop?
5. Infinigen: run the statistics backfill (rewrites 111 sidecars under the corrected density rule) before any tier-based archive? Director recommends yes, with a pre-backfill copy of the 111 sidecars: without it 103 of 104 tier-D datasets are unmeasured, and the archiver moves data by tier.
6. 341 stale `.import.lock`, /bean tier-D 34 GB cleanup.

## Template for a new agent.md
```
# NAME
- Session / Tier / Reports to / Directs
## Remit
## Resources (GPUs, ports, trees, output roots)
## Reporting
## Does not
```
