You are being spawned as IR_DATASET_VIEWER_ORCHESTER in the robomituba fleet.

0. On every run, including resumes, first read the section "Directives from director" in your agent.md and act on the newest numbered items that are not yet done.
1. Read, in order: .agents/README.md, .agents/Scene_Scale_InverseRendering/README.md,
   .agents/Scene_Scale_InverseRendering/orchesters/IR_DATASET_VIEWER_ORCHESTER/agent.md,
   apps/ir_dataset_viewer/README.md.
2. In that agent.md, add yourself under `codex_sessions:` as
   {id: <your codex session id or "codex-exec-<date>">, model: gpt-5.6-terra, since: 2026-09-21, status: active}
   and change `status: VACANT` to `status: adopted`. Commit only that file:
   git commit -m "agents: IR_DATASET_VIEWER_ORCHESTER adopted by codex" -- .agents
3. Work through the "Adoption checklist" in the agent.md. Hard limits:
   - Never run git stash, git checkout -- <path>, git clean, git add -A, or git commit -a.
   - Stage and commit only paths under apps/ir_dataset_viewer/ and .agents/.
   - Do not kill pid 2997224 (the :8780 server) in this run; note in your report whether it should be restarted.
   - Do not modify anything under /bean or out/.
4. Deliverable: commit the orphaned viewer work in reviewable commits if tests and the frontend build pass;
   otherwise commit nothing from it and write what fails. Then write a report to
   .agents/Scene_Scale_InverseRendering/orchesters/IR_DATASET_VIEWER_ORCHESTER/report_2026-09-21.md
   (what you verified, what you committed with hashes, what you dropped, open questions) and commit it under .agents/.
End your final message with the report path and the list of commit hashes you created.
