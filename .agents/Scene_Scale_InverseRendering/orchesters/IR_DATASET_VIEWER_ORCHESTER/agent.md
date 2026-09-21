---
# Sessions currently bound to this role file. Append a row when a new session
# (Claude peer, Codex, other) adopts the role; do not delete rows, mark them ended.
bound_sessions:
  - kind: claude-peer
    name: (d2 lineage, name unknown)
    ref: unknown
    address: none
    since: 2026-09-03
    status: ended        # session died ~2026-09-20; server pid 2997224 outlived it
  # - kind: claude-peer          <- the new orchester fills this row on adoption
  #   name: IR_DATASET_VIEWER_ORCHESTER
  #   ref: <ListAgents ref>
  #   address: <uds socket>
  #   since: <date>
  #   status: active
codex_sessions:
  - id: 01a0c1d2-bab0-74f3-a89b-2a73de593205
    model: gpt-5.6-terra
    since: 2026-09-21
    status: failed      # codex exec (workspace-write): bwrap pivot_root not permitted in this
                        # container, zero commands ran. Needs a host where bwrap works or a
                        # user decision on sandbox mode. Prompt: director scratchpad codex_viewer/prompt.md
  - id: codex-exec-2026-09-21
    model: gpt-5.6-terra
    since: 2026-09-21
    status: active
ensure_session: false   # Codex thread, not a Claude session; ensure_sessions.sh skips it
last_reviewed_by: DIRECTOR_MARK10 [c3cb4e]
last_reviewed: 2026-09-21
status: adopted
---
# IR_DATASET_VIEWER_ORCHESTER

- **Project:** Scene_Scale_InverseRendering (IR)
- **Session:** Codex thread 01a0c1d2-bab0-74f3-a89b-2a73de593205 (gpt-5.6-terra), adopted 2026-09-21. Resumed by the user with `codex exec resume`.
- **Tier:** orchester
- **Reports to:** PROJECT_DIRECTOR (DIRECTOR_MARK10 [c3cb4e])
- **Directs:** may request a shared worker (SONNET_WORKER_1/2) for read-only checks; both are currently loaded

## Why this role exists
The session that owned `apps/ir_dataset_viewer/` died around 2026-09-20 and left its
work uncommitted in the shared checkout. IR_DATASET_HSSD_ORCHESTER rescued a copy; nobody
has reviewed or adopted the work. You inherit it.

## Remit
- Own `apps/ir_dataset_viewer/` (Svelte 5 frontend + `backend/catalog.py`, `controller.py`,
  `server.py`). Standalone viewer for `ir_principled_dataset.v2` under `/bean/ir_dataset`
  and `out/ir_dataset`; read-only except the explicit out→/bean publish workflow.
- First job: triage, review, and either commit or discard the orphaned work (below).
- Then: keep the viewer usable for IR_PIPELINE / HSSD / ABO orchesters as their corpora grow.

## Inherited state (verify before acting; this was true 2026-09-21 01:50Z)
- **Uncommitted in the shared tree** (last viewer commit c211eee, 2026-09-06):
  8 modified tracked files, +754/−122, and 2 untracked files
  `src/MiniJobStatus.svelte`, `src/MiniMap.svelte`.
  Content: catalog rows gain `capture_kind` / `camera_pose_source`; App.svelte gains a
  draggable heading compass (1.5 px/deg), pixel panel, mini map, mini job status;
  `style.css` +255; `tests/test_catalog.py` +16.
- **Rescue copy:** `/bean/ir_dataset_work/rescued_d2_viewer_work_20260920/`
  (`tracked_files.patch`, the two .svelte files, README with restore steps).
  Restore = `git apply tracked_files.patch` + copy the two files into `src/`.
- **Server:** `python3 apps/ir_dataset_viewer/server.py --port 8780`, pid 2997224, parent init,
  started 2026-09-06 by IR_DATASET_INFINIGEN_ORCHESTER's transcript (established 2026-09-21 from
  /proc environ), still answering 200. Coordinate any restart with that orchester and the director. It runs the code as it was
  at start, not the working tree. Do not kill it without checking who is using :8780
  (other orchesters may browse it); announce to the director first.
- Dev server (`run_dev.sh`) uses vite polling on :5174 because the NFS mount exhausts inotify.

## Adoption checklist
1. Read this file, `../../README.md`, `../../../README.md`, and `apps/ir_dataset_viewer/README.md`.
2. Confirm the working tree still matches the rescue copy: `git diff -- apps/ir_dataset_viewer | diff - <rescue>/tracked_files.patch`.
3. Run `apps/ir_dataset_viewer/tests/` against the working tree; build the frontend (`npm run build`).
4. Review the diff for intent. Split into reviewable commits if it holds; otherwise report what
   fails to the director with a recommendation (commit / partial / discard).
5. Never `git stash`, `git checkout -- .`, or `git clean` in this tree (NFS root_squash makes
   stash unrecoverable; the untracked files exist nowhere else but the rescue copy).
6. Commit only `apps/ir_dataset_viewer/` paths. The shared checkout has 160+ other modified
   files from other sessions; `git add -A` or `git commit -a` stages peers' work.
7. Report to the director: what was committed, what was dropped, whether :8780 was restarted.

## Directives from director (read at the start of every run; newest last)
1. 2026-09-21 03:10Z — Run 1 outcome accepted: rescue verified, check+build pass, 118/121 tests,
   nothing committed. Correct call.
2. The 3 failures in `tests/test_nir_passive.py` come from an UNCOMMITTED change to
   `apps/render_ir_principled_dataset_queue.py` (+10/−6, mtime 2026-09-06 04:37, same era as the
   viewer work, no other session claims it). Treat it as part of the same orphan. Your scope now
   includes that file and its fixtures. Do: read its diff, decide whether the `storage_profile`
   default change (CORE_HALF_EXR_V1 → V2) is intended, update the three test fixtures to pass
   `storage_profile` explicitly (do not weaken the tests), rerun the full viewer suite.
3. If the suite is green: commit in this order, each its own commit, viewer paths and that one
   queue file only: (a) backend/catalog.py + test_catalog.py, (b) the two new .svelte components,
   (c) App.svelte + other src changes + style.css, (d) render_ir_principled_dataset_queue.py + fixture
   updates. Append the hashes to your report.
4. Do not restart :8780 yet. Instead record in the report: which pids/sessions have connections
   to :8780 (`ss` is not installed; use `lsof -i :8780` or /proc/net/tcp), and whether
   `/api/datasets` times out because of NFS scanning or a hung process.

5. 2026-09-21 05:20Z — SUPERSEDES the queue-file part of 2 and 3(d): the storage_profile change in
   `apps/render_ir_principled_dataset_queue.py` and the three `test_nir_passive.py` failures are now
   owned by IR_DATASET_INFINIGEN_ORCHESTER (it owns the :8780 server; both came from one stash pop).
   Do not edit that file or those fixtures. Once that orchester reports the suite green, do 3(a)-(c)
   for the viewer diff only. Until then: item 4 only (who is connected to :8780, why /api/datasets stalls).

6. 2026-09-21 06:30Z — IR_DATASET_INFINIGEN_ORCHESTER reports the suite green at d77d7cc (175 passing).
   Item 5's wait is over: do 3(a)-(c) for the viewer diff now, then item 4. Verify green yourself
   first (`python3 -m pytest apps/ir_dataset_viewer/tests`); if not green, stop and mail me.

## Resources
- No GPU claim. The viewer's render queue can request up to 3 GPUs per dataset via the daemon;
  do not enable that path without a lock claim agreed with the director.
- Ports 8780 (backend) and 5174 (dev frontend).

## Does not
- Modify dataset artifacts under `/bean/ir_dataset` or `out/ir_dataset` (publish workflow excepted).
- Touch other sessions' modified files in the shared checkout.
