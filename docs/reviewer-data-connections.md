# Reviewer redesign: data connections

Task: the reviewer redesign handoff of 26 November 2026. This page maps every element of the
synthetic reviewer prototype (`src/sentra/reviewer/prototype.html`) to the Sentra source that
would supply it with real data. It records what works with today's code, what needs new
adapter code, what needs new data or processing, and which decisions belong to the owner.

The prototype uses fictional people only. `src/sentra/reviewer/field_map.json` lists every
displayed field with its dataset, provider field path, canonical metric and board key.
`tests/test_reviewer_prototype.py` checks each reference against the code, so a renamed
dataset, field path, board key or rule fails CI.

## Reviewer page with real data

The private viewer has a **Reviewer** page (`sentra.viewer_app.reviewer_page`). It shows this
design with the signed-in user's real data, behind the viewer's Google sign-in, access decision and
transfer reservations. The page is never published as a public link. The static prototype stays the
public demo.

- **Server side** (`sentra.reviewer.live`): individual rows are the published board days of people the
  user may see individually (for the team, people in the team scope; withdrawn consent is left out).
  Board values pass through unchanged and missing stays missing. Group figures are computed on the
  server from group contributors with `organization.group_summary` and `trends.group_trend` over the
  `trends.publishable_end` window. Only values leave the server: a statistic below five contributors
  is empty and carries no count, and an empty day looks the same as a hidden one. Codes and device
  labels must match Sentra's formats, and every `<` in the embedded data is escaped.
- **Page**: the same file runs in live mode when the viewer fills its data slot. Personal comparisons,
  signals and assessment states come from the board (`*_b`, `f`, `lvl`, `a`, `m`); the browser
  recomputes nothing. Coverage shows processed values per day. Minute-level detail loads on request on
  the Sleep and Daily activity pages.
- **Decisions applied for now** (owner may change them): codes only, no names; the group median; the
  configured refresh time (01:30 Beirut, paused with collection); no device issue date or "Before
  device issued"; no daytime heart rate; workouts open on the Workouts page.
- **Checks**: `tests/test_reviewer_live.py` (payload scope, suppression without counts, escaping, and a
  live walkthrough) and the Reviewer row in `tests/test_privacy_matrix.py` (every user type,
  withdrawal and sharing reduced to group-only).

## Live verification

`scripts/reviewer_live_check.py` checks which of these sources actually hold data. Not run yet.

```text
python scripts/reviewer_live_check.py --org ORG_ID --secrets .private/reviewer-live-check.toml
```

- **Authorization and budget.** Operator only, with a file holding just the read-only `[viewer]`
  section. The hosted app's secrets (with `[auth]`) are refused, so the November hosted-viewer
  allowance is never used. Every read reserves the ordinary viewer allowance first. Verify the
  egress baseline and headroom first (operating guide). The run stops before
  `--max-transfer-bytes` (default 8 MB).
- **Scope.** One organization: participants with a current, non-withdrawn consent in an open
  membership, the same population that may count towards that organization's group figures.
  Database reads are filtered to them. The published board is a single file, filtered after
  download. With fewer than five contributors the check stops before reading data.
- **Output.** Board fields with a non-null value (zero counts, null does not) and their share of
  days, dataset rows, person-days by each dataset's documented day (sleep by wake day, WHOOP cycles
  and recoveries by cycle start, vendor daily values by civil date; rows without a day are never
  counted), requested coverage, request failures in the last 30 days and consent totals. Any count
  below five prints as "fewer than 5", and every figure derived from such a group is withheld.
  Dates are those reached by at least five people. No participant IDs, names or readings.
- **Sharing.** Team private channel or the task owner only, never this public repository or its
  pull requests and issues. Record only the conclusions here.

## Status key

| Status | Meaning |
| --- | --- |
| Ready | An existing `ViewerReader` method or board field supplies it; only display code is needed |
| Adapter | The data is stored and readable; new reviewer code must read or reshape it |
| New data | Needs a processing, refresh or collection change before it can appear |
| Decision | Needs an owner decision before any implementation |

## Who may see what

Every read goes through `sentra.viewer_reader.ViewerReader`, constructed with the access
decision from `sentra.access.resolve` (team operators see everyone; organization users see their
own organization, individuals only with `individual` sharing, groups with at least five eligible
contributors). `board()` keeps only people the user may view individually; `group_board()` keeps
eligible group contributors. Detail reads call `_permitted()` first. Each read reserves transfer
budget before rows leave the database, and detail selections stop above 10,000 rows or 20 MB.

The officer views follow the same scope. People who share group figures only never appear in the
directory, the coverage list or grid, observations or any profile or detail page. A group-only
code and an unknown code open the same "no individual profile" page, so neither is confirmed. A
group figure or trend day below five eligible contributors is hidden without saying how many
contributed. The walkthrough test checks each of these.

**A replacement for Streamlit must keep these checks on a server.** A static page with embedded
data cannot enforce consent, withdrawal or organization boundaries. The prototype is static only
because its data is synthetic.

## Overview

| Element | Source | Status | Notes |
| --- | --- | --- | --- |
| Last successful update | board `built_at`, `data_through`, `source_run` via `ViewerReader.board()` | Ready | The wellness refresh is scheduled at 01:30 Beirut (`wellness.yml`); a 3:00 p.m. update is a schedule change (**New data**) |
| Worth a look, 7 days | board `people[].days[]`: `f` flags, `lvl`, `a`, `m`, values and `*_b` baselines | Ready | Read the last seven board days per person instead of only the latest (`observations.py` explains one day). Board days exist only for usable days, so a non-usable day never produces an observation |
| Personal comparison | board `sleep_b`, `rhr_b`, `hrv_b`, `sleep_hr_b`, `steps_b` | Ready | Same 28-day, 7-reading baseline as `pipeline.baselines` |
| Coverage: readings present | measurement rows per dataset and day | Adapter | `catalog()` gives only the latest reading per dataset. A per-day count needs a bounded aggregate query, or (better) a coverage block published by the refresh |
| Coverage: Not requested | `audit.connection_state.covered_intervals` via `ViewerReader.status()` | Adapter | A day outside every requested interval |
| Coverage: Request failed | `audit.collection_runs.details.failures` via `status()` | Adapter | Failures carry dataset and start date |
| Coverage: No readings returned | requested day with no measurement rows | Adapter | An empty response alone does not explain why |
| Coverage: Delayed sync | latest reading time from `catalog()` against successful recent runs | Adapter | A heuristic label; wording to confirm |
| Coverage: Device not worn | `wear_min` in `daily_features` | New data | The board drops unusable days, so zero-wear days never reach it. Publish per-day wear and coverage for every day |
| Coverage: Before device issued | none | Decision | Sentra stores no issue date; `org.memberships.joined_on` is the nearest field |
| Group: last night's sleep, steps yesterday, resting HR | `group_board()` + `organization.group_summary` / `trends.group_trend` | Ready | Per device, five contributors per statistic. Sentra uses the median of per-person medians; the handoff proposes an average (**Decision**) |
| Group: WHOOP steps | none | Ready (as unavailable) | WHOOP cycle steps are not mapped (`metric_map.UNMAPPED` lists the gap) |
| Group trend: daytime HR | `daily_features.hr_mean` covers all worn minutes, not a daytime window | New data | Publish `hr_mean` or a daytime mean on the board; agree the window. WHOOP has no daytime series |

## Participant profile

| Element | Source | Status | Notes |
| --- | --- | --- | --- |
| Code, device | board `id`, `device` | Ready | `device` is set only when all readings come from one provider (board-2) |
| Name | none | Decision | `sql/007` stores no names, locations or contact details |
| Enrolled date | `org.memberships.joined_on` | Adapter | `organization_rows()` reads consent only; add a bounded membership read |
| Device issue date | none | Decision | Needed for Before device issued |
| 30 days / Since 1 Oct | board rows | Ready | History before a person's first import exists only after bounded, authorized imports (1–30 days per run) |
| Today so far (partial steps) | none | New data | Daily collection requests completed days only (`daily_plan.request_days` ends before today). Intraday reads need a new cadence and budget, or the requirement is dropped |
| Latest reading time | `catalog()` `latest_point_time`, `latest_interval_end` | Ready | Per dataset, from returned records |
| Sleep, HR and HRV, other vitals | board `sleep`, `deep`, `rem`, `rhr`, `hrv`, `br`, `temp`, `spo2`, baselines | Ready | Missing values stay absent |
| Activity | board `steps` (Fitbit minute sum), `strain` (WHOOP) | Ready | Label the step source; the vendor daily total is a separate stored dataset |
| Workouts | `exercise` (Fitbit) and `workout` (WHOOP) records via `records()` | Adapter | Stored, not processed; WHOOP zone field path to confirm from stored records |
| Vendor scores | board `rec`; WHOOP sleep performance via `measurements()` | Ready / Adapter | Fitbit returns no recovery or strain score |
| Coverage strip per measure | as in the coverage rows above | Adapter | |

## Measurement detail

| Element | Source | Status | Notes |
| --- | --- | --- | --- |
| Fitbit night: stages | `measurements()` on dataset `sleep`, metrics `/sleep/stages/N/{type,startTime,endTime}` | Adapter | Reuse the parsing in `processing.observations.google_sleep` |
| Fitbit night and day: minute HR | `measurements()` on `minute_heart-rate`, `/heartRate/beatsPerMinuteAvg` | Ready where collected | Imports plan minute data for the last 7 days of each window; the November pilot scope collected none. Minute detail on every day needs a retrieval decision and cost estimate (**New data**) |
| Fitbit day: minute steps | `measurements()` on `minute_steps` | Ready where collected | As above |
| Fitbit day: vendor totals | `daily_steps`, `daily_distance`, `daily_total-calories`, `daily_active-zone-minutes` | Adapter | Stored, not processed |
| Original-resolution HR | `original_heart-rate` | Decision | One representative day per import; a backfill is an open scope decision |
| WHOOP night | `records()` on `sleep` + `recoveries()` | Ready | Stage totals, breathing, performance, recovery, score status |
| WHOOP cycle | `records()` on `cycle` | Ready | Cycle interval is a physiological day |
| Units, resolution, field names | `measurements()` rows (`unit`, `resolution_description`, `metric`) | Ready | |
| Source reference | `manifests()`; `original()` for the unchanged response | Ready | Originals can contain identifiers and stay operator-only |
| Date navigation, return position | client state | Ready | No data dependency |

## Work to connect real data

1. **Reviewer adapter (no new data).** A server-side module that builds the overview, profile
   and detail view models from `board()`, `group_board()`, `catalog()`, `status()`,
   `measurements()`, `records()` and `recoveries()`, under the existing access decision.
2. **Refresh additions (board-3).** Publish, for every day including unusable ones, per-dataset
   coverage and Fitbit wear minutes, plus a daily HR mean. This removes per-day coverage queries
   from the viewer and supports Device not worn.
3. **Collection and schedule.** Minute datasets in the daily scope, October history in bounded
   batches, a 3:00 p.m. refresh, and intraday reads for today's partial values. Each needs a cost
   estimate against the transfer allowance and operator authorization before any live change.
4. **Owner decisions.** Name source, device issue dates, average or median, gap wording, original
   resolution beyond minute data, and the framework that replaces Streamlit while keeping the
   access checks server-side.
