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

## Current board (2026-09-23 05:30Z)
| Agent | State | GPUs | Workers |
|---|---|---|---|
| IR_PIPELINE_ORCHESTER | roll-call pending; worker reports v16_appearance training alive (v14 arms concluded, outcome not yet on file) | 4,5,7 | SONNET_WORKER_1 liveness watch |
| IR_DATASET_HSSD_ORCHESTER | 90/100 at 04:26Z, 0.76/h, ETA 09-23 17Z; 12 of 88 below 15 takes (supply-limited); retry-loop bug fixed df63cfc | 0,2,3 (GPU 0 co-located for IR evals, never handed over) | SONNET_WORKER_1 (6h heartbeat), SONNET_WORKER_2 (final sweep armed) |
| IR_DATASET_ABO_ORCHESTER | abo_cornell_env_v1 FINAL-CANDIDATE 60 scenes / 4,340 frames (top-up done 09-21 10:50Z); completion notice to IR_PIPELINE sent 09-23 (2 days late), nir_model corrected to derived_pseudo_nir; take-ceiling study done | 1,6 idle 2 days → RELEASE ordered 09-23 | SONNET_WORKER_2 verified 0 mismatches |
| IR_DATASET_INFINIGEN_ORCHESTER | statistics backfill running since 09-21, 174 writes vs 111 baseline, suspect loop → stuck-vs-slow check ordered; tier run not done; :8780 restart deferred; apartment hover 260 poses unvalidated, no GPUs; Codex worker never reached it | none | none |
| IR_DATASET_VIEWER_ORCHESTER (Codex) | viewer work committed 09-21; terminal since repurposed by the user to draft a Memory-NIR paper | none | — |
| RESEARCHER (Codex) | v14 review assigned 09-21 06:00Z, NOTHING delivered in 2 days; process alive, terminal blank | none | — |
| OPTICALNAV_ORCHESTER | 20272904 exported+verified 09-21 (78 GB); Drive holds 9 scenes; 20267404 rendering on Device 1, 83% at 02:37Z, auto-export at target; 20273004 export has 1 corrupt Stokes frame (re-render optional) | none (daemon :8765 idle) | SONNET_WORKER_1 readiness + health |
| OPTICALNAV_NAVIGATION_ORCHESTER | idle; 20273004 in-room nodes are NOT a wall issue (walls non-blocking by design; nodes from pre-restore motion grid) | none | none |
| PC_OPTICALNAV_RENDER | 20267404 active-polar sweep in progress | Device 1 GPU 0 | — |
| PC_WORKER_1 | free, user-assigned only | Device 1 | — |
| SONNET_GPU_MANAGER | no task from user since 09-21 | none | — |
| CODEX_IR_DATASET_INFINIGEN_WORKER | still in Workers worktree; never contacted its orchester | none | — |

## Open items for the user (2026-09-23)
1. ABO: is 60 scenes / 4,340 frames the final abo_cornell_env_v1? Take ceiling: only removing massing blocks adds takes (+32%); halving +11%; hover-chain 1 is −21%.
2. Infinigen: (a) 229 GB two-root duplication — is a published dataset a snapshot or a live copy? (b) delete 62 superseded versions? (c) spend Stage-1 bake time on 5 work-room scenes (hours) and 13 apartments (days) before any hover frame renders? (d) backfill result once its stuck-vs-slow check lands.
3. Navigation: (a) 20273004's 25 in-room nodes — regenerate grid (24+ min, invalidates 250 episodes) or leave; prior question: should empty-room walls block paths? (b) commit 4 tool files + 8 tests. (c) 341 stale .import.lock, /bean tier-D 34 GB.
4. HSSD: ~98 GB v3 blends deletion, askable only after the corpus completes (~17Z today).
5. RESEARCHER produced nothing in 2 days. Director will read its terminal and either re-prompt or retire the role; your call if you want it kept.
6. CODEX_IR_DATASET_INFINIGEN_WORKER: move to IR_DATASET and point it at the Infinigen orchester (commands in its agent.md), or close it.
7. Infinigen scripts orphan (7 modified + 6 untracked, 2026-09-09): assign or drop.
8. `.agents/` mode 777 inherited from NAS; tighten?

## Template for a new agent.md
```
# NAME
- Session / Tier / Reports to / Directs
## Remit
## Resources (GPUs, ports, trees, output roots)
## Reporting
## Does not
```
