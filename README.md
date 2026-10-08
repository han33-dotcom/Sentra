# FYP — Wellness & Safety

Final-year project exploring institutional health and safety through consumer wearable data. No first customer industry has been selected. **Stage 4: daily cloud collection is complete; Stage 5 viewer implementation has been reviewed and approved for publication**, with private hosted acceptance pending deployment. The pipeline has one Fitbit Air participant and one WHOOP participant using an existing membership. The final use case will be chosen after the team measures what data is available and how timely it is.

Read the [Stage 0 feasibility report and implementation checklist](docs/stage-0-feasibility.md), [Stage 1 setup/status](docs/stage-1-setup.md) and [schema review](docs/schema.md). Stage 1 acceptance checks passed on 8 October 2026: a Python CLI, encrypted local authorization/sample storage, a PostgreSQL schema draft, and real authorization, populated samples and token renewal for Google Health (`sentra-510913`) and WHOOP. Google Testing mode still requires reconnecting after seven days. Manual Fitbit export ingestion remains a fallback if later access checks fail; it does not provide automated daily updates. Subsequent stages require explicit approval.

## Project workspace

- [FYP project home and task board](https://app.notion.com/p/3e87b9b98086806d973efef0204f2e7b)
- [Plan 1](https://app.notion.com/p/3e87b9b98086819296bef0a655f38961)
- [Decisions and open questions](https://app.notion.com/p/3e87b9b9808681eaa878f5634c60801c)

Notion holds the shared plan, tasks, meetings, and decisions. This repository holds code, setup instructions, made-up example data, and reviewed changes. Link a code change from its Notion task.

## First milestone

Establish reproducible authorization and retrieval for WHOOP, verify the existing Google Health project's Fitbit access, document the manual-export fallback, and define a reviewable audit schema. Subsequent stages will establish a data dictionary and findings on missing data and arrival delay. The team then chooses one FYP question and an evaluation method with supervisor input.

## Working rules

- Assign one owner to each Notion task and define what "done" means.
- Work on a branch for each code change and ask a teammate to review it.
- After each stage, report completion, changes, checks, open dependencies and the next stage, and propose a commit message. Wait for explicit approval before committing/pushing and before starting the next stage.
- Do not commit raw wearable records, credentials, tokens, or consent documents. Use synthetic examples in the repository.
- Confirm ethics and approved storage requirements with the supervisor before using participant data as research findings.

Follow [Stage 1 setup](docs/stage-1-setup.md) to install and authorize accounts, then [Stage 2 collection instructions and evidence](docs/stage-2-collection.md) to import, resume, inspect status, verify sources and create private extracts. [Stage 3 storage instructions and evidence](docs/stage-3-storage.md) cover deployed Supabase Free storage, private originals, separate collector/viewer permissions, quota stops and encrypted backup restoration. [Stage 4 collection instructions and evidence](docs/stage-4-collection.md) cover cloud credential ownership, recovery, midnight Beirut scheduling and the publication/acceptance gate. [Stage 5 viewer instructions](docs/stage-5-viewer.md) cover private sign-in, filters, audit evidence, CSV/original downloads, capacity and free hosting. Its code is reviewable locally; hosted acceptance awaits private deployment and actual teammate/visitor checks. Read the capacity finding before enabling ongoing minute-data collection.

The planned Stage 7 observation is now a [three-day initial audit](docs/stage-7-audit-plan.md), with preliminary findings and existing imports retained. It starts only after Stages 4–6 and explicit approval of the observation period. Further collection beyond that window requires review and approval; the capacity guards remain in force.
