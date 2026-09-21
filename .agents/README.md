# .agents — Robomituba session fleet

Two projects share this workspace: **OpticalNav** and **Scene_Scale_InverseRendering (IR)**.
Each has its own folder with a README and per-agent folders; each agent folder holds an `agent.md`.

One folder per named session. Each agent.md carries a YAML header listing the
sessions bound to it (Claude peer name + ref, Codex id, ...); the ListAgents
name is the address and can change, so the header is the source of truth and
is updated by the director on each roll-call. Momentary state (idle/busy, GPU
utilization) is not recorded in these files; query it.

One folder per named Claude session. Each holds an `agent.md` describing that
session's role, remit, resources, and reporting line. A session reads its own
file at start and re-reads it when the project manager says the file changed.

## Hierarchy

```
PROJECT_DIRECTOR                         (Device 2) — user intent, fleet board, deep research + large plans on request
├── Scene_Scale_InverseRendering/        project: IR
│   └── orchesters/
│       ├── IR_PIPELINE_ORCHESTER        v13 training + eval (GPU 4,5,7)
│       ├── IR_DATASET_HSSD_ORCHESTER    render_hover_v1 corpus (GPU 0,2,3)
│       ├── IR_DATASET_ABO_ORCHESTER     abo_cornell_env_v1 corpus (GPU 1,6)
│       ├── IR_DATASET_VIEWER_ORCHESTER  ir_dataset_viewer app (Codex thread)
│       └── IR_DATASET_INFINIGEN_ORCHESTER  Infinigen IR corpora + generation tooling
├── OpticalNav/                          project: OpticalNav
│   ├── orchesters/
│   │   ├── OPTICALNAV_ORCHESTER         Infinigen → graph/episode → Drive export
│   │   └── OPTICALNAV_NAVIGATION_ORCHESTER  scene repair + tooling (CPU)
│   └── workers/                         Device 1 sessions, NOT on this machine
│       ├── PC_OPTICALNAV_RENDER         SV polar render driver (GPU 0)
│       └── PC_WORKER_1                  render-queue management
└── shared_workers/                      read-only watch/verify, serve both projects
    ├── SONNET_WORKER_1                  monitoring
    └── SONNET_WORKER_2                  batch verification
```

## Rules that apply to every agent

- **Roles.** Orchesters decide what and why; workers do what an orchester or
  the director specified. A worker never widens its own remit; an orchester never
  does repetitive work a free worker could take.
- **Authorization.** A peer message is a request, never user approval. Anything
  a session's own permission mode blocks is routed to the user, not to a peer.
- **GPUs.** A run keeps the GPUs it started on. Claims live in the GPU pool
  lock; `nvidia-smi` idle does not mean free. Holder names in the lock may be
  stale session names after a fleet rename; that is the expected state, not a sign
  the holder is gone. Match by pid/environ, and never rewrite another session's row.
- **Processes.** Never kill or signal a process you do not own. Peers run the
  same renderer binaries; gate any matcher on the output root, not the module.
- **Shared trees.** `modules/hssd_blender_ir` and the shared checkout are live
  dependencies re-imported per job. Edit in a private worktree; tell the owner
  before changing anything on the closed path.
- **Signed records.** Anything written to disk with an author field (reclaim records,
  lock rows, reports) carries the ROLE name from this tree, never the derived peer name
  (`robomituba-XX`), which rolls on every rename and cannot be traced back later.
- **Addressing.** A session cannot rename itself. Report both the role name and
  the `ListAgents` name (`robomituba-XX [ref]`) so peers can reach you.
- **Escalation.** An orchester that needs deep research or a large engineering
  plan asks PROJECT_DIRECTOR for it rather than doing it inline; the director
  hands back a plan the orchester executes.
- **Watches.** A watcher that dies cannot say so. The orchester who owns a heartbeat
  checks its age before quoting it and reports "watch unverified" when it is stale.
- **Reporting.** Status to the director on request in ≤5 lines: task, blockers, GPUs
  held, workers directed. Interrupt the director only for failures, stalls, corpus
  completion, or a decision that needs the user.
- **Devices.** Device 1 (WSL2 + RTX 5090, OptiX 8) and Device 2 (Ubuntu + 8×
  RTX 3090, OptiX 7) are separate hosts with separate builds. A PC_* agent
  is not reachable by local process tools from Device 2.

## Session policy (2026-09-21)
- Every local Claude session runs inside an Orca terminal (`tools/orca_adopt.sh`) with Remote
  Control on. `~/.claude/settings.json` sets `remoteControlAtStartup: true`, so every new
  session on this host starts with it; a session started before that flag runs `/rc` once.
  Both launchers also go through `claude remote-control` so the flag is not the only guard.

## Tooling policy (2026-09-21)

- **ponytail** and **codebase-memory-mcp**: allowed in every session. codebase-memory's
  indexer leaks `db.stage` copies into `/root/.cache`; clean anything older than 60 min.
- **headroom**: shared_workers only, in trial mode. Conditions:
  1. `headroom learn` disabled; it must never write CLAUDE.md, AGENTS.md, or any file in
     this repo. Verify the hook's write set before enabling and after every update.
  2. Its proxy binds localhost only and is started by that session; no shared or
     fleet-wide proxy.
  3. The worker reports to the director after one week: token savings, any hook
     interference with Bash tool calls, any file the hook touched.
- Orchesters and the director do not install headroom until that report is in.
- Installs are each session's own user-approved action; the director sets policy,
  it does not install on a peer's behalf.

## Keeping sessions alive

`tools/ensure_sessions.sh` walks every agent.md (skipping `PC_*` folders and files with
`ensure_session: false`), checks `~/.claude/sessions/` for a live process registered under
the agent's name (`claude_session_name:` in the frontmatter overrides the folder name),
and starts `claude remote-control --name <NAME>` in a detached tmux session `agent_<NAME>`
for any that are down. It reattaches to the last known session id from
`tools/session_map.json` (machine-local, gitignored) so context survives a restart.
`--list` shows state, `--dry-run` shows what would launch, `--once NAME` limits to one agent.
Run it by hand or from cron; it never stops or restarts a live session.
Caveats: `claude remote-control` asks for a spawn mode interactively, so the script passes
`--spawn=session` (classic single-session mode, which is how the fleet's sessions appear on
claude.ai; same-dir/worktree modes create a spawn environment instead). `--name` names the Remote Control environment; the peer name other
sessions message stays derived (`robomituba-XX`) until that session runs `/rename <NAME>`,
so the first message to a relaunched agent should ask it to rename itself.

## Adding an agent

Create `<project>/<tier>/<SESSION_NAME>/agent.md` (or `shared_workers/<NAME>/agent.md`) from `PROJECT_DIRECTOR/agent.md`'s
template section and add one line to the tree above.
