# Sentra architecture

Task: [SEN-32](https://github.com/han33-dotcom/Sentra/issues/32). This is the current system in one
place, for the team and for whoever takes it over. It links to the detailed documents rather than
repeating them. The `stage-*` documents are the history of how it was built; where they differ,
this page and the documents it links are current.

Everything here is synthetic-safe: no participant data, credentials or private configuration.
Secrets, custodian details and recovery locations stay in the restricted operator inventory
([service account handoff](service-account-handoff.md)).

## Components and where they run

| Component | Code | Runs on | Database identity | What it does |
| --- | --- | --- | --- | --- |
| Collector | `sentra.cloud_run`, `.github/workflows/collect.yml` | GitHub Actions, 00:00 Beirut (**paused**) | `sentra_collector` | Requests bounded date ranges from Google Health and WHOOP, keeps every original response, loads records and measurements ([operating guide](operating-guide.md)) |
| Original responses | — | Supabase Storage, private bucket `sentra-originals` | written by the collector | Unchanged, compressed, hash-keyed responses; never modified |
| Audit tables | `sql/001`–`006`, `009` | Supabase PostgreSQL, schemas `audit` and `collector_private` | — | Records, measurements, sessions, coverage and collection runs; private collection cursors and controls ([schema](schema.md), [data dictionary](data-dictionary.md)) |
| Organization tables | `sql/007`, `008`, `010`, `011` | Supabase PostgreSQL, schemas `org` and `enrollment_private` | — | Organizations, officers and reviewers, memberships, consent history and follow-ups (`org`); invitations, sign-in identities and sessions (`enrollment_private`) ([participation permissions](participation-permissions.md)) |
| Enrollment service | `sentra.enrollment_web`, `src/sentra/enrollment/` | Render (Free, Frankfurt), `/join` | `sentra_enrollment` | Participants join from an invitation link, choose sharing, connect a wearable and manage or withdraw ([self-service enrollment](self-service-enrollment.md)) |
| Daily wellness refresh | `sentra.wellness_refresh`, `.github/workflows/wellness.yml` | GitHub Actions, 01:30 Beirut (paused with collection) | `sentra_viewer` to read; collector storage account to write | Builds parquet tiers, runs processing and publishes `board/board.json` in the private bucket `sentra-tiers` ([wellness board](wellness-board.md)) |
| Processing | `sentra.processing` | Inside the refresh, or the operator's Compose `processing` container | `sentra_viewer` | v0 daily wellness features, flags against each person's own baseline, and k-anonymous group statistics ([processing](processing.md), [indicator contract](indicator-contract.md)) |
| Private viewer | `viewer/app.py`, `sentra.viewer_app` | Streamlit Community Cloud, private app | `sentra_viewer` (read-only) | Team pages (daily activity, sleep, workouts, availability, board) and organization pages: overview, profiles, trends, follow-ups. Reports (SEN-42) are in review |
| Follow-up writes | `sentra.follow_up_store`, `sql/010` | Called by the viewer | `sentra_followups` (two functions only) | The only write path from the viewer; every rule rechecked in the database ([follow-ups](follow-ups.md)) |
| Read API | `sentra.api` | Operator's Docker Compose, `127.0.0.1` | none (reads processed files) | Read-only team-operator API over processed outputs; one shared key, no organization scope ([read API](read-api.md)) |
| Backups and recovery | `sentra.shared_backup`, `sentra.recovery` | Operator's machine | admin, run by the operator | Encrypted health-only backups, offline verification, isolated restore ([retention policy](retention-policy.md), [recovery rehearsal](recovery-rehearsal.md)) |
| Project website | `website/`, `.github/workflows/website.yml` | GitHub Pages, from `main` | none | Public project website; no data |
| Team workflow | `.github/workflows/ci.yml`, `pr-policy.yml`, `team-*.yml` | GitHub Actions | none | Tests on Linux and Windows, data guard, PR policy, project board and Slack signals ([team workflow](team-workflow.md)) |

## Data flow

```
Google Health v4 / WHOOP v2
  -> collector (GitHub Actions, paused)          -> sentra-originals: original responses
                                                 -> audit.*: records, measurements, sessions, runs
Participant phone -> enrollment service (Render) -> org.*: memberships, consent history
                                                 -> enrollment_private.*: invitations, identities, sessions
audit.* --(wellness refresh, read-only)--> sentra-tiers: parquet tiers -> processing -> board/board.json
Private viewer (Streamlit, read-only):
  team pages      <- audit.*, board/board.json
  org pages       <- board/board.json, org.* consent, follow-ups   (access decided per page load)
  follow-up write -> sentra_followups functions only
Processed files -> read API (operator, 127.0.0.1) -> team tools
```

## Database identities

| Role | May | May not |
| --- | --- | --- |
| `sentra_collector` | Write audit tables and original objects; use the collection controls; list enrolled connections through one function | Read organization or enrollment tables directly |
| `sentra_viewer` | Read audit and organization tables. Reserve egress through `public.sentra_reserve_viewer_egress`, which updates the private budget through a restricted function | Modify health or organization rows or directly write to the egress budget |
| `sentra_enrollment` | Write enrollment and consent rows and encrypted provider credentials | Read health rows |
| `sentra_followups` | Execute the two follow-up functions | Anything else |

Passwords are set privately by the operator and never committed. Each migration says which role
applies it and in what order.

## Migrations

| File | Adds |
| --- | --- |
| `001_foundation.sql` | The `audit` schema and its tables |
| `002_permissions.sql` | The collector and viewer roles and their grants |
| `003_numeric_precision.sql` | Exact numeric projections from the preserved JSON |
| `004_daily_collection.sql` | Private cursors and the daily-collection control |
| `005_viewer_status.sql` | Aggregate usage and safe status fields for the viewer |
| `006_parquet_tiers.sql` | The private `sentra-tiers` bucket for derived tiers |
| `007_organization_access.sql` | The `org` schema: organizations, users, memberships, consent history |
| `008_self_service_enrollment.sql` | The enrollment role; invitations, participant sign-in identities and sessions; encrypted provider credentials |
| `009_compact_series.sql` | Lossless compact series (additive; nothing deleted) ([storage plan](storage-plan.md)) |
| `010_follow_ups.sql` | Follow-ups, their append-only history and the follow-up role |
| `011_fitbit_link_invites.sql` | Separate links for existing Fitbit participants to use hosted sign-in |

Which migrations are applied on the hosted project is an operator record, kept with the hosted
configuration, not in this repository.

## Privacy boundaries

- **Pseudonyms** (`p01` …) identify participants in normalized data, published wellness
  outputs, organization views and downloads, and the read API. Team operators can also
  download unchanged provider responses from **Audit details** in the private viewer. Those
  originals can contain identifying fields and stay operator-only
  ([participation permissions](participation-permissions.md#data-categories)).
- **One access module** (`sentra.access`) decides what each signed-in viewer user sees: team
  operators see everyone; organization users see their own organization only, individuals only
  with `individual` sharing, and group statistics only with at least 5 contributors each. The
  decision is rechecked on every page load, so withdrawals and sharing changes apply on the next
  load ([organization overview](organization-overview.md)).
- **Read-only health and organization access.** The viewer, the refresh's reads and processing
  use `sentra_viewer`. The guarded egress function records reservations on a separate connection
  so they persist even if the read fails. Follow-up changes use the separate `sentra_followups` role.
- **Bounded and guarded.** Every read reserves egress before rows leave the database, and storage
  and database ceilings are checked before collection ([operating guide](operating-guide.md)).
- **Wellness, not medical.** Rules are provisional until the medical expert signs them off
  ([medical evidence](medical-evidence.md)).
- **Evidence.** The [privacy checks](privacy-checks.md), [evaluation table](evaluation.md) and
  [limitations](limitations.md) record what has been verified and what has not.
