# Robomituba Notion Workspace

> Runtime registry for the Robomituba Notion workspace. This file contains no
> credentials. Replace each `UNCONFIGURED` value only after the matching Notion
> database or page is created and shared with the integration.

## Metadata

- Status: live for Research Hub — six database registries verified; optional project pages pending
- Refreshed at: 2026-08-24T03:00:00Z
- Maintainer: Robomituba team
- Source of truth: repository Markdown under `docs/`, `dev_report/`, and `notes/`
- Policy: store links and manifests for rendered artifacts; do not upload EXR,
  NPZ, or `out/` render batches to Notion.

## Database Registry

| logical_name | data_source_id | title_property | key_properties | status_property | date_property | purpose |
|---|---|---|---|---|---|---|
| documents | 946f8e9e-d8e3-4164-b57b-427736ffb99a | Name | Type, Area, Source Path, Tags, Review Date | Status | Review Date | Index of canonical repository documents and their review state |
| experiments | 5b442703-d5c1-4e64-9763-29ed7a29f74d | Name | Scene, Component, Git Revision, Result, Artifact Path | Status | Run Date | Render, pBRDF, optical-navigation, and performance experiment log |
| decisions | 9b6491a3-9902-4f95-8790-148cc5119f80 | Name | Area, Decision, Alternatives, Repository Record | Status | Decision Date | Architectural and operational decision record |
| milestones | 2f6a186f-5212-481a-95bc-238a089e35dc | Name | Area, Owner, Deliverable, Repository Link | Status | Target Date | Workstream milestones and releases |
| tasks | 43a97603-a7fb-431e-8f61-b9f859c9b126 | Name | Milestone, Priority, Evidence Path, Notes, Owner | Status | Due Date | Kanban task management linked to active research milestones |
| references | 94c2fea1-db84-4893-abad-44c40cff76a3 | Title | Authors, Year, Kind, URL, Relevance | Reading Status | Added Date | Papers, datasets, standards, and external technical references |

## Database Schemas

### documents

```text
Name (title, required)
Status (select): Draft | Active | Needs review | Archived
Type (select): README | Design | Runbook | Report | API | Dataset card | Decision
Area (multi-select): Bridge | Converter | Navigation | Mitsuba | WebUI | Assets | Operations
Source Path (url or text, required): repository-relative path or canonical URL
Tags (multi-select)
Review Date (date)
Summary (text)
```

### experiments

```text
Name (title, required)
Status (select): Planned | Running | Complete | Blocked | Invalidated
Run Date (date)
Scene (select or relation)
Component (multi-select): Rendering | pBRDF | OpticalNav | Dataset export | Daemon | WebUI
Git Revision (text)
Result (select): Pass | Fail | Inconclusive
Artifact Path (text): job, manifest, report, or dashboard link; never binary upload
Finding (text)
```

### decisions

```text
Name (title, required)
Status (select): Proposed | Accepted | Superseded | Rejected
Decision Date (date)
Area (multi-select): Bridge | Converter | Navigation | Mitsuba | Infrastructure | Documentation
Decision (text)
Alternatives (text)
Consequences (text)
Repository Record (text): link to docs/ or dev_report/ entry
```

### milestones

```text
Name (title, required)
Status (select): Planned | In progress | Blocked | Complete
Target Date (date)
Area (multi-select): Bridge | Converter | Navigation | Mitsuba | WebUI | Documentation
Owner (people or text)
Deliverable (text)
Repository Link (text)
```

### tasks

```text
Name (title, required)
Status (select): Backlog | Next | In progress | Review | Blocked | Done
Milestone (relation): one active Research Hub milestone; two-way as `Tasks`
Priority (select): High | Medium | Low
Evidence Path (text): report, commit, manifest, or reproducible repository path
Notes (text)
Due Date (date, optional)
Owner (people, optional)
```

### references

```text
Title (title, required)
Reading Status (select): Inbox | Reading | Cited | Archived
Added Date (date)
Authors (text)
Year (number)
Kind (select): Paper | Dataset | Standard | Documentation | Repository
URL (url)
Relevance (text)
Tags (multi-select): Rendering | Polarization | BRDF | Navigation | USD | Mitsuba
```

## Project Pages

| name | page_id | url | purpose |
|---|---|---|---|
| Robomituba Project Hub | 3c6e09c8-20b7-8151-bbcb-ce48a2532ce0 | https://app.notion.com/p/3c6e09c820b78151bbcbce48a2532ce0 | Independent Research Hub: current priorities, evidence boundaries, six research-management databases, and linked task board |
| Documentation Home | UNCONFIGURED | UNCONFIGURED | Curated entry point for repository documentation |
| Render Operations Dashboard | UNCONFIGURED | UNCONFIGURED | Daemon status, render batches, and experiment summaries |

## Operating Rules

1. Repository documents are canonical; Notion is the navigable operational index and team-facing summary.
2. Every Notion experiment entry links to a reproducible request, manifest, commit, or report path.
3. Record device-specific Mitsuba environment facts in experiment entries: hostname, GPU/compute capability, driver, Python, `PYTHONPATH`, variants, and plugin path.
4. Never commit a Notion token. Keep `NOTION_API_TOKEN` only in a user-local environment or secret manager.
5. Before an agent writes to Notion, replace the matching `UNCONFIGURED` identifiers and validate property names against the live database.

## Maintenance Log

- 2026-08-24 | Created project-specific Notion registry scaffold; live integration and database IDs are pending. | Codex
- 2026-08-24 | Verified the existing RGB-NIR inverse-rendering project page as the Robomituba Project Hub. | Codex
- 2026-08-24 | Created and verified the independent Robomituba Research Hub with Documents, Experiments, Decisions, Milestones, and References databases; legacy Project DB remains untouched. | Codex
- 2026-08-24 | Added the independent Tasks Kanban database with two-way Research Hub milestone links, six initial tasks, and Hub board views; legacy Project/Tasks DB remains untouched. | Codex
- 2026-08-24 | Added the 2026-08-17–23 weekly research report to Documents, recorded Polar transport and IR showcase experiments as Inconclusive pending GPU/scene-scale evidence, and linked evidence notes to the active milestones and tasks. | Codex
- 2026-08-24 | Added three evidence-driven Tasks (Polar fixtures, representative OpticalNav Stokes, IR showcase acceptance) and two Accepted Decisions (physical-path Stokes default; deterministic IR diversity contracts). | Codex
