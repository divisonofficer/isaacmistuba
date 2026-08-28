# Notion workspace setup

This project uses Notion as an operational documentation index. Repository files
remain canonical; Notion holds summaries, ownership, status, decision records,
and links to reproducible artifacts.

## One-time connection

1. Create a Notion internal integration at <https://www.notion.so/my-integrations>.
2. Store its token in a user-local secret, for example `NOTION_API_TOKEN`; never
   add it to Git, `NOTION_WORKSPACE.md`, shell history, or issue comments.
3. Create a parent page named **Robomituba Project Hub** and share it with the
   integration using **Add connections**.
4. Under that page, create the six databases described in
   [`NOTION_WORKSPACE.md`](../NOTION_WORKSPACE.md): Documents, Experiments,
   Decisions, Milestones, Tasks, and References.
5. Share every database with the integration. Copy each database data-source ID
   and project-page ID into `NOTION_WORKSPACE.md`.
6. Connect the Notion MCP service to the agent, then perform a read-only smoke
   test before enabling create or update actions.

## Recommended views

- **Project Hub:** linked views for Active milestones, Running/Blocked
  experiments, and Proposed decisions.
- **Documents:** filter `Status != Archived`, grouped by `Area`, sorted by
  `Review Date` ascending.
- **Experiments:** grouped by `Result`, sorted by `Run Date` descending; include
  Scene, Component, Git Revision, and Artifact Path.
- **Decisions:** filter `Status = Accepted` for the default view, with a second
  view for Proposed items.
- **Tasks:** Kanban grouped by `Status`; link every task to one active Research
  Hub milestone and move work through Backlog, Next, In progress, Review,
  Blocked, and Done.
- **References:** Inbox and Cited views, grouped by `Kind`.

## Operating boundary

Do not upload raw render outputs, EXR files, NPZ files, GPU caches, or full
`out/` batches to Notion. Use a stable repository-relative path, job ID,
observation manifest, export path, or external storage link instead.

## Completion check

The Research Hub configuration is live when the Hub and all six database
registries have verified Notion IDs and a read-only query succeeds through the
connected Notion MCP service. Optional project pages may remain
`UNCONFIGURED` until their specific workflow is introduced.
