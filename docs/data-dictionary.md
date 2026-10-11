# Wearable metric dictionary and private Notion inventory

The executable provider/dataset/path dictionary is
[metric_dictionary.py](../src/sentra/metric_dictionary.py), verified against
[Google v4 fields](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints),
[Google aggregation](https://developers.google.com/health/aggregate-data), and
[WHOOP v2](https://developer.whoop.com/api/) on 10 October 2026.
The viewer exposes labels, original/display units, classification, explanations
and references. Exact path matching prevents similarly named fields from inheriting
an unrelated definition. Unmapped fields stay discoverable in Audit details.

Documented duration units convert to hours/minutes; HRV milliseconds are not
durations. Distance may display in kilometres while retaining millimetres/metres.
Google protobuf exercise durations retain their exact seconds string. WHOOP
asleep duration is a labelled Sentra sum of light + slow-wave + REM only when
all inputs exist and are scored. Session elapsed duration uses physical instants,
including pauses; no civil date is converted into an invented instant.
WHOOP recovery joins sleep by `sleep_id`, with no date-based substitution.

Copy this structure into a private Notion database. Record definitions from official
provider documentation and distinguish them from observed API behavior. Keep
participant agreement, credentials, health files and identifying information out
of this repository. Use participant IDs and private manifest/extract references.

| Property | Meaning / example format |
| --- | --- |
| Provider / dataset | Google Health `daily_steps`; WHOOP `recovery` |
| Vendor metric | Exact returned field / JSON pointer |
| Vendor definition | Meaning and official source link; unknown if unverified |
| Value kind | Measurement, vendor summary, vendor calculation, vendor score, Sentra calculation or unknown |
| Standardized unit / vendor unit | Preserve both; do not infer an undocumented unit |
| Timestamp basis | Physical point, vendor interval, associated cycle interval or vendor civil date |
| Requested resolution | Daily/minute aggregation, original API record or session summary |
| Observed resolution | Sampling interval statistics; distinguish API aggregation from sensor sampling |
| Requested history / observed history | Separate requested range from returned records |
| Availability evidence | Returned, explicit null, unscored, provisional, failed fetch, unsupported with evidence or uncertain |
| Coverage / gaps / corrections | Requested page coverage, observed fields, candidate gaps and change evidence |
| Delivery delay | Observation timestamp minus measurement/interval time where meaningful; pending until observed |
| Source reference | Endpoint, requested range/resolution, private response ID and collection time |
| Candidate feature | Possible derived indicator plus required fields and limitations; not a validated health claim |
| Findings status | Preliminary / pending observation / reviewed; owner and review date |

Initial examples for definition review (not longitudinal findings):

- Google daily step totals are vendor summaries; minutes are separately requested
  aggregation. Counts of fields/records across providers are not directly comparable.
- WHOOP recovery/strain are vendor scores; session heart-rate summaries do not provide
  continuous heart-rate readings. Preserve score state before interpreting absence.
- API originals are unchanged responses, not raw physical sensor signals.

The human now researches retained data after a bounded three-day backfill;
ongoing collection is deferred and no formal elapsed-day audit is required.
Coverage, arrival delay, correction rates and candidate-feature
findings must be supported by actual evidence, not an elapsed-day claim.
Two participants on different
devices do not establish population accuracy or validate health predictions.

## Extra Fitbit datasets (October 2026, not yet collected)

Three Google Health v4 LIST datasets were added to the job plan in priority order.
They are requested in the same weekly batches as the other Google LIST datasets
(one-day jobs for daily recovery), with `pageSize=1000`, the `google-wearables`
source family, and every `nextPageToken` followed.

| Priority | Dataset | Record type | Filter field ([filters](https://developers.google.com/health/filters)) | Scope ([data types](https://developers.google.com/health/data-types)) |
| --- | --- | --- | --- | --- |
| 1 | `sedentary-period` | Interval | `sedentary_period.interval.start_time` | `activity_and_fitness.readonly` |
| 2 | `respiratory-rate-sleep-summary` | Sample | `respiratory_rate_sleep_summary.sample_time.physical_time` | `health_metrics_and_measurements.readonly` |
| 3 | `activity-level` | Interval | `activity_level.interval.start_time` | `activity_and_fitness.readonly` |

The current authorization already requests `activity_and_fitness`, `sleep` and
`health_metrics_and_measurements`, so no reconnect is needed for these datasets.
Respiratory-rate sleep summaries need `health_metrics_and_measurements`, not
`sleep`.

Normalization is unchanged. Returned paths stay as vendor JSON pointers:
- `/respiratoryRateSleepSummary/{full,deep,light,rem}SleepStats/breathsPerMinute`
  are breaths/min vendor calculations.
- `standardDeviation` and `signalToNoise` have no documented unit, so they stay
  `unknown` and are kept unchanged.
- `/activityLevel/activityLevelType` keeps the returned enum text.
- Interval start/end fields stay in the record.

The viewer shows the breathing-rate labels in **Daily activity**. For interval
datasets it shows Sentra calculations:
- **Sedentary time** and **Time sedentary / lightly / moderately / very active**
  are the sum of returned intervals from one source that start on the Beirut day.
- Days with no returned periods show *Not returned*, never zero.
- Overlapping or invalid intervals show *Not summed*.
- Unknown activity-level enum values are not reclassified.
- Several sources on one day stay *Multiple returned values*.

### Job outcomes

Hosted runs now record a separate outcome for every job, both in
`collector_private.daily_jobs.progress.outcome` and in the
`audit.collection_runs.details.outcomes` counts:

| Outcome | Meaning |
| --- | --- |
| `records` | All pages followed; at least one record returned |
| `no_records` | All pages followed; the provider returned no records (not a zero measurement) |
| `denied` | HTTP 401 after one forced token refresh, or HTTP 403 (scope/consent/permission) |
| `failed` | Any other fetch, validation, storage or planning failure; progress retained for resume |

### Bounded probe (manual, October 3–9 2026)

Scheduled collection stays paused. This probe is a manual `recovery` dispatch of
the existing collector workflow on the feature branch, one dataset at a time in
priority order. The end date is exclusive. Run `activity-level` for one day first,
because its record density is unknown.

```powershell
gh workflow run collect.yml --repo han33-dotcom/Sentra --ref feat/fitbit-extra-datasets -f mode=recovery -f provider=google_health -f start=2026-10-03 -f end=2026-10-10 -f dataset=sedentary-period
gh workflow run collect.yml --repo han33-dotcom/Sentra --ref feat/fitbit-extra-datasets -f mode=recovery -f provider=google_health -f start=2026-10-03 -f end=2026-10-10 -f dataset=respiratory-rate-sleep-summary
gh workflow run collect.yml --repo han33-dotcom/Sentra --ref feat/fitbit-extra-datasets -f mode=recovery -f provider=google_health -f start=2026-10-09 -f end=2026-10-10 -f dataset=activity-level
# only after checking the one-day activity-level size:
gh workflow run collect.yml --repo han33-dotcom/Sentra --ref feat/fitbit-extra-datasets -f mode=recovery -f provider=google_health -f start=2026-10-03 -f end=2026-10-09 -f dataset=activity-level
```

Each run prints one line per job, `<dataset> <date>: complete (records|no_records)`
or `denied`/`failed`. Existing capacity and egress guards apply before every
fetch. Measure the actual storage cost per dataset afterwards from an operator
checkout:

```powershell
.venv/Scripts/sentra.exe shared-growth
```

### Storage estimate per type (before the probe)

The estimate uses synthetic records normalized by the current code: compact
record JSON plus measurement rows. It is in decimal MB and **excludes** index and
table overhead; `shared-growth` reports the observed overhead factor.

| Dataset | Rows per record | ≈ bytes per record | Assumed records/participant-day | ≈ MB per participant-day | ≈ MB for Oct 3–9 |
| --- | --- | --- | --- | --- | --- |
| `sedentary-period` | 1 record + 4 measurements | 6,300 | 15–40 | 0.09–0.25 | 0.7–1.8 |
| `respiratory-rate-sleep-summary` | 1 + 4 | 6,450 | 1–3 | 0.01–0.02 | 0.05–0.14 |
| `activity-level` | 1 + 5 | 7,600 | 50–300 (unknown) | 0.4–2.3 | 2.7–16 |

Original compressed responses add roughly 0.1–0.3 KB per record. At the last
recorded snapshot, about 92 MB remained before the import limit. If
`activity-level` returns per-minute intervals (≈1,440/day), it would cost about
11 MB per participant-day. That is why it is probed for one day first.

If daily collection is re-enabled before a probe has created coverage, each new
dataset is reported as a planning `failed` outcome ("No initial coverage"). It is
never silently backfilled.
