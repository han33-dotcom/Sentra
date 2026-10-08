# Stage 2 — local collection and initial import

The authorized scope is two consenting participants, institutional health and
safety data inspection, and local extraction/audit tools. Google Health v4 is
working for the existing Sentra project and Fitbit account; WHOOP v2 is working
for the membership account. No legacy Fitbit integration or manual fallback is
needed for these demonstrated connections. API enablement alone remains weaker
evidence than the real authenticated imports. No service has been provisioned,
scheduled job installed, paid resource enabled or AI/health score added.

## Run and review

Use the Stage 1 virtual environment and authorized `config/local.toml`. Run from
the repository root in PowerShell:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests
.venv/Scripts/python.exe -m sentra.cli initial-import all --start 2026-09-08 --end 2026-10-08
.venv/Scripts/python.exe -m sentra.cli status google_health
.venv/Scripts/python.exe -m sentra.cli status whoop
.venv/Scripts/python.exe -m sentra.cli verify-import google_health
.venv/Scripts/python.exe -m sentra.cli verify-import whoop
.venv/Scripts/python.exe -m sentra.cli export whoop --dataset sleep
.venv/Scripts/python.exe -m sentra.cli export google_health --dataset minute_heart-rate
.venv/Scripts/python.exe -m sentra.cli export-originals whoop
```

`--end` is exclusive. With no dates the window is the previous 30 calendar days,
ending at today's Beirut midnight. Supply the same dates when resuming so the
request plan stays fixed. Completed jobs are skipped; failed/incomplete jobs
resume their last durable cursor. `--dataset` can be repeated to narrow an import.
If a later completed request fully covers an earlier failed/interrupted range,
the old attempt is marked `superseded` and linked to that completed request;
its failure/history and original objects are retained. It is not relabeled as
successful. Run snapshots preserve the individual job outcomes.
`initial-import all` runs providers independently and sequentially; failures in
one do not prevent the other being attempted. Imports and exports share a local
private-directory lock: run one writer at a time. Read-only status and integrity
checks use atomic snapshots. A busy writer exits with an actionable message.

To revisit corrections rather than skip completed windows:

```powershell
.venv/Scripts/python.exe -m sentra.cli initial-import whoop --start 2026-09-08 --end 2026-10-08 --dataset recovery --recheck
```

Normalized exports are streaming **gzip-compressed JSON and CSV**, with sessions
and coverage included. The CLI prints their paths below `.private/exports`.
Open a gzip archive with a local archive tool, or use Python's `gzip.open` to read
it. Downloads are sensitive even when IDs are pseudonymous. Do not commit them,
publish them in Notion, or send them outside the agreed team. There is no browser
viewer yet; that is Stage 5. Original-response exports include a compressed
manifest and exact decompressed API bytes, including provider identity fields.
They exclude OAuth state, keys and credentials. The normalized CSV quotes strings
that could execute as spreadsheet formulas; JSON retains the exact vendor value.

## Selected requests

| Provider | Datasets | History / requested resolution |
| --- | --- | --- |
| Google Health | Steps, distance, total calories, active-zone minutes, active minutes, heart rate | 30 days, provider daily rollups; one-day windows inside requests bounded to seven days |
| Google Health | Daily resting HR, HRV, oxygen saturation, respiratory rate, sleep temperature derivations, VO2 max | 30 days, original daily records, seven-day request batches |
| Google Health | Sleep and exercise | 30 days, original session records, seven-day batches and all pages |
| Google Health | Steps, distance, total calories, active-zone minutes, heart rate | Last seven days, requested 60-second vendor rollups, one physical day per request |
| Google Health | Heart rate | Last completed day, original API resolution, all pages |
| WHOOP | Cycles, recovery, sleep, workouts | 30 days, original vendor records and all pages, 25 per page |

“Original API response” means the unchanged response body. It does **not** mean
physical raw sensor signals. Daily/minute rollups are vendor summaries. WHOOP
offers summary/session scores and heart-rate summaries, not a continuous HR
stream. Requested 60 seconds does not guarantee every minute is returned.
Original HR is a representative initial audit sample, not a commitment to
recurring daily original-resolution collection.

Physical ranges use `Asia/Beirut` zone rules, including 23/25-hour DST days.
Google daily summaries preserve provider civil dates, which can differ from
Beirut during travel; they do not fabricate UTC timestamps. Sleep uses its
documented end-time filter; exercise uses civil start dates. WHOOP's start/end
selection follows its collection endpoints, so a returned boundary-overlapping
cycle need not correspond to exactly one calendar day.

Most Google requests specify `google-wearables`. Google sleep LIST rejects that
source-family parameter: sleep requests omit it and preserve **all returned
sources**, including possible edits, with original provenance. No returned sleep
record is silently filtered. Live checks also established that daily-list filters
need snake_case field paths although one documentation example uses camelCase.

## Records, meaning and provenance

Each normalized record retains all nonidentity vendor fields, provider/session
IDs, original timestamps, dataset, participant ID, collection time, resolution
description and original-response reference/pointer. All returned fields survive
in the compressed originals, including identities omitted from normalized output.
Unknown scalar fields remain inspectable with unknown meaning/unit. Source and
timing metadata stay in record context/vendor fields rather than being duplicated
as measurement rows. All such fields remain inspectable. No unit or measurement
time is inferred from a field name alone. `created_at`, `updated_at`
and collection time are not substituted for measurement time.

Mapped fields currently include original HR (beats/min), HR summaries and resting
HR (beats/min), HRV (ms), steps, distance (mm), calories (kcal), active minutes,
sleep durations, WHOOP strain/recovery/sleep scores and selected WHOOP summaries.
Units stay in the vendor's documented form; no kcal-to-kJ conversion is applied.
Active-zone minutes are vendor credits, not physical minutes of activity. Values
are explicitly classified as measurement, vendor summary, vendor calculation,
vendor score or unknown. Int64 vendor strings remain intact alongside normalized
numeric values. A vendor HR estimate is still a device measurement, not a claim
of clinical accuracy. Field definitions are a starting dictionary, not a completed
observation audit. The [updated initial observation plan](stage-7-audit-plan.md)
uses three days and labels findings preliminary.

WHOOP recovery refers to its cycle. Reads/exports resolve recovery intervals from
the currently stored cycle and include that cycle's response reference, so cycles
arriving later or corrected later repair the timing without another recovery
request. Without a linked cycle, timing stays explicitly unresolved.

Stable record keys use provider IDs where available; unnamed Google points use
datatype, source and original time. Mutable values and interval end times are
excluded, allowing corrected values/removed fields to replace the same record.
Different datasets/resolutions remain distinct. Rechecks retain fetch manifests
per observation while identical raw bodies reuse one content-hashed object.

`complete` means the requested API window was traversed to its final page. It
does not prove device wear, complete measurement coverage or final scoring.
Empty successful responses, null returned fields, unscored WHOOP records and
failed requests remain distinguishable. Unsupported/missing causes are not
guessed from empty responses. Records remain provisional during this stage.

## Durability, privacy and limits

SQLite operates in memory with individually compressed records. Shared metric
context is stored once and restored for exports. Its authenticated encrypted,
compressed snapshot is atomically replaced at each page checkpoint. Original
response objects are compressed/encrypted separately and deduplicated by hash.
The key stays in the OS credential store; tokens retain Stage 1's separate vault
and refresh lock. A raw object written just before interruption may be unreferenced
until retry; it is retained and reused, never deleted automatically.

Manifest, normalized records and cursor commit together. Partial page writes do
not advance progress. A fresh process can resume. Expired cursors restart one job
once; repeated tokens/malformed pages stop without complete coverage. HTTP reads
allow four attempts for transient failures, bounded waits and one safe access-token
renewal. Long Retry-After delays stop for a later manual resume. Refresh-token
requests are not blindly retried. Errors/logs omit response bodies and secrets.

Local private storage defaults to 200 MiB; `--max-private-mib` accepts 1–200 MiB.
Usage includes credentials, raw objects, snapshots and explicit extracts. Writes
check capacity and 64 MiB free-disk headroom, including temporary snapshot copies.
Compressed exports stream under quota checks and publish only after completion;
capacity failure removes partial export files. Imports stop safely and retain
durable progress, with a nonzero exit status. No automatic deletion or limit
increase occurs. Review usage and backup before deciding which obsolete explicit
extracts to remove. This local ceiling is **not** enforcement of future Supabase
quotas; those need separate Stage 3 measurement and controls.

The OS account/filesystem remains a trust boundary. Local snapshots are encrypted;
explicit extracts are compressed but unencrypted. Shared team access, collector
permissions, backup/key transfer, free-project pausing and hosted capacity controls
remain Stage 3 work. Google Testing-mode refresh expiry still requires reconnecting
after seven days unless the project authorization configuration is changed.

## Official request references (checked 8 October 2026)

- [Google supported data types](https://developers.google.com/health/data-types)
- [Google LIST filters, source restrictions and paging](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/list)
- [Google physical rollups](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/rollUp)
- [Google civil daily rollups](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/dailyRollUp)
- [Google record definitions](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints)
- [Google distance units](https://developers.google.com/health/reference/rest/v4/DistanceRollupValue), [calorie units](https://developers.google.com/health/reference/rest/v4/TotalCaloriesRollupValue), [active minutes](https://developers.google.com/health/reference/rest/v4/ActiveMinutesRollupValue), [active-zone minutes](https://developers.google.com/health/reference/rest/v4/ActiveZoneMinutesRollupValue)
- [Google rate limits](https://developers.google.com/health/rate-limits)
- [WHOOP v2 API and field definitions](https://developer.whoop.com/api/)
- [WHOOP rate limits](https://developer.whoop.com/docs/developing/rate-limiting/)

## Acceptance evidence

Stage 2 acceptance checks passed on **8 October 2026**, on `ETL-pipeline`.

- Initial requested history: 8 September through 8 October (exclusive), Beirut
  boundaries; seven completed days of minute aggregates; 7 October original HR.
- Google: all **106 current planned jobs** complete; **61,656 normalized records**,
  including **37,348 original HR samples over 38 pages**, 26 sleep records and
  11 exercise records. Common daily datasets each returned 25 records; active-zone
  summaries returned 21. Oxygen-saturation and VO2-max queries returned no records.
  These are observations of the selected API window, not explanations of absence.
- WHOOP: all four jobs complete; **31 cycles, 30 recoveries, 30 sleeps, 46 workouts**.
  Every collection traversed both returned pages. WHOOP's interval filtering can
  include boundary-overlapping cycles; a 30-day query need not yield 30 cycles.
- Representative original HR: returned intervals had minimum 1 s, median 2 s,
  maximum 1,117 s; one interval exceeded 60 s. This is observed API cadence and
  gaps for one day, not a device-accuracy or health finding.
- Fresh-process reruns skipped 106 Google and four WHOOP jobs, with unchanged
  record counts. A bounded Google recheck of 41 jobs updated the documented unit
  mappings without changing record counts. Correction/removal behavior itself
  was demonstrated with synthetic fixtures; comparison to app values remains
  Stage 6 work.
- Verified **286 Google fetch manifests / 156 distinct original bodies** and eight
  WHOOP manifests/bodies, including content hashes, counts and source references.
  Original-download bytes matched every exported manifest hash.
- Full Google extracts matched **61,656 records / 138,141 scalar measurement
  rows**. The filtered WHOOP sleep extract matched **30 records / 780 rows**.
  Both normalized and original extracts were tested with actual authorized data.
- Private local storage after demonstrated extracts: **76.18 MiB of 200 MiB**.
  This includes encrypted imports, originals, credentials and explicit extracts;
  it is not an estimate of PostgreSQL usage. Stage 3 must measure hosted sizes.
- **43 synthetic tests passed**, covering paging/empty pages, resume, corrected
  records, repeated/expired/malformed cursors, atomic snapshot failures, source
  corruption, privacy, DST, retries, provider isolation and quota/export failures.
  Dependency check, compilation and Git whitespace check passed. Secrets, health
  stores and extracts are ignored by Git. Independent code review findings were
  repaired and checked; its follow-up found no remaining important defects.

An initial checkpoint scan race and Google request incompatibilities were found
with real requests, fixed, and resumed without losing durable progress. A slow
full-export quota scan was reproduced and replaced with byte accounting under
the private writer lock plus final actual-size validation. Only that interrupted
export's own staging files were removed; imports and completed extracts remained.

No Stage 2 integration is blocked for the current accounts. Google Testing-mode
reconnect requirements remain. No recurring collection, hosted storage or team
browser has been demonstrated yet. Stage 3 will add private Supabase storage,
permissions, measured hosted capacity controls, and backup/restore procedures.
**Stop here until the user explicitly approves Stage 3.**
