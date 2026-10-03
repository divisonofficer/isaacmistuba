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

## Current board (2026-09-30 05:00Z, after the 04:18Z machine reboot)
| Agent | State | GPUs | Workers |
|---|---|---|---|
| IR_PIPELINE_ORCHESTER | idle; v26c/d/e (v25 RGB+NIR as-image, 320px×8 views, walking v2 + registration-aware pointmap losses) finished 09-29/30 exit 0. Finding: on 24-view walks pose drift dominates (0.43 m → 0.18 m with rigid-cycle); 1–3-view val cannot see it and overfits. bf16 GT-rounding fix queued | 5,6,7 (DDP, 10-03) | none |
| IR_DATASET_HSSD_ORCHESTER | hover_v1 100/100; walk_v1 148/150; walk_v2 COMPLETE 10-02 20:07Z: 149 done / 1 no-walk / 0 failed (136 glassag + 13 plain trees), lighting augmentation 149/149; completion sent to IR_PIPELINE, v7 trains on all 149. NIR spp MIXED: 67 scenes at 384, 82 at 192 (speed switch 10-01 16:42Z); indirect clamp 10 in all 149 (never changed) | none (released all 10-03 06:36Z; walk_v2 presumably complete, confirmation asked) | — |
| IR_DATASET_ABO_ORCHESTER | abo_cornell_env_v2 (props-24, hosts 3) LIVE 32/50, queue relaunched 04:30Z, self-clears claims | 4 (new text-legibility corpus, 10-03) | — |
| IR_DATASET_INFINIGEN_ORCHESTER | apartment 4-pass corpus: 2,953 frame dirs, 0 of 9 sets complete by contract; 9 dead claims released; nothing running; :8780 restarted on committed code pid 22812 (pinned to 1,3,6, max 3) | 1,3 (bake + geometry profile, 10-03) | — |
| OPTICALNAV_ORCHESTER | Drive holds 18 verified scenes; 20267404 + 4 others exported since 09-23; 20268504 re-export in flight after polar re-render (exporter substring-match bug fixed, uncommitted); daemon :8765 dead, not needed | none | SONNET_WORKER_1 to re-arm |
| OPTICALNAV_NAVIGATION_ORCHESTER | idle; 369 stale .import.lock deleted 09-24; tier-D 34 GB reassigned by user to another peer | none | none |
| PC_OPTICALNAV_RENDER / PC_WORKER_1 | Device 1: 20268504 finished 09-29; unaffected by Device 2 reboot | Device 1 | — |
| SONNET_WORKER_1 | revived; re-arming after owner confirmation | — | — |
| SONNET_WORKER_2 | revived; both tracks closed cleanly (ABO v1 09-21, HSSD hover sweep 09-23: 22,683 frames clean); nothing to re-arm | — | — |
| SONNET_GPU_MANAGER | revived; found the reboot; holding all lock rows as claimed-unbound until owners answer (HSSD/ABO/INFINIGEN have) | — | — |
| Codex threads | viewer, RESEARCHER, Infinigen worker all died with the reboot; respawn from role files when wanted | — | — |

## Open items for the user (2026-09-30)
1. CLOSED by events: walk_v2 finished with clamp 10 throughout and NIR spp split 67@384 / 82@192 (manifests carry render_knobs, so the split is recoverable per frame). The clamp bias (35–45% of lamp-lit NIR light lost) is now a property of the whole corpus; any fix is a re-render decision, not a setting.
2. IR_PIPELINE: widen the walking probe to 12+ takes first? Then D+F (rigid-cycle + SE3 Kabsch) vs D+E with 24-view walking val. GPUs 4,5,7 idle until answered.
3. GPU allocation (10-03, GPU manager verified): Infinigen [1,3] (apartment bake + geometry-profile workers), ABO [4] (new text-legibility corpus, CPU phase first), IR_PIPELINE [5,6,7] (DDP training, 100%). HSSD released everything 10-03 06:36Z. GPUs 0 and 2 unheld. Nothing to decide.
4. Infinigen: (a) restart the 2,219-frame flash backlog (two renderer bugs fixed first: --resume+--stage re-rendered finished frames; Stager overwrote pose_selection.json, damaged 20263004/hover)? (b) large_residence excluded: generate new --room-scale scenes? (c) 17 dark3r blends judged unusable (deformed primitives, no textures, no Factory names): drop them?
5. OpticalNav: delete the old 20268504 Drive run after the re-export verifies (already asked by that session).
6. Navigation: 20273004 grid regen vs leave (walls non-blocking by design); commit 4 tool files + 8 tests.
7. HSSD: ~98 GB v3 blends. Director now recommends KEEP: hssd_ir_prepared_v3.blend is the input of every re-render, relight and augmentation run (last used 10-03 06:30Z); deleting it closes those paths, including any clamp fix. HSSD is raising it with its user with that flag.
8. Boot resilience: nothing on Device 2 restarts on reboot (Tailscale, Orca, daemons). Add a boot script for Tailscale + Orca? Agent jobs stay manual.
9. Codex roles: respawn viewer / RESEARCHER / Infinigen worker, or retire?
10. Older, still open: Infinigen 229 GB two-root duplication and 62 superseded versions; Infinigen scripts orphan (7+6 files); `.agents/` mode 777.

## Template for a new agent.md
```
# NAME
- Session / Tier / Reports to / Directs
## Remit
## Resources (GPUs, ports, trees, output roots)
## Reporting
## Does not
```
