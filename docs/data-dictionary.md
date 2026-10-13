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

## Extra Fitbit datasets (October 2026)

Three Google Health v4 LIST datasets were added in priority order. They follow every
`nextPageToken`, with `pageSize=1000` and the `google-wearables` source family.

| Priority | Dataset | Record type | Filter field ([filters](https://developers.google.com/health/filters)) | Scope ([data types](https://developers.google.com/health/data-types)) | Planning |
| --- | --- | --- | --- | --- | --- |
| 1 | `sedentary-period` | Interval | `sedentary_period.interval.start_time` | `activity_and_fitness.readonly` | Weekly batches; daily and recovery plans |
| 2 | `respiratory-rate-sleep-summary` | Sample | `respiratory_rate_sleep_summary.sample_time.physical_time` | `health_metrics_and_measurements.readonly` | Weekly batches; daily and recovery plans |
| 3 | `activity-level` | Interval | `activity_level.interval.start_time` | `activity_and_fitness.readonly` | **On request only** |

`activity-level` is never part of the daily, initial or recovery plans (`ON_REQUEST`
in `src/sentra/datasets.py`). A manual run includes it only when it names the dataset,
for example `-f dataset=activity-level` with `mode=recovery`. Its measured cost is about
22.9 MB of database per participant-day, which the current headroom cannot sustain.
Any further collection waits for a reviewed storage reduction plan.

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

Hosted runs record a separate outcome for every job, both in
`collector_private.daily_jobs.progress.outcome` and in the
`audit.collection_runs.details.outcomes` counts:

| Outcome | Meaning |
| --- | --- |
| `records` | All pages followed; at least one record returned |
| `no_records` | All pages followed; the provider returned no records (not a zero measurement) |
| `denied` | HTTP 401 after one forced token refresh, or HTTP 403 (scope/consent/permission) |
| `failed` | Any other fetch, validation, storage or planning failure; progress retained for resume |

### Bounded probe results (October 3–9 2026)

Manual `recovery` runs on `develop`, provider `google_health`, one dataset per run,
in October 2026. End dates are exclusive. Scheduled collection stayed paused.

| Dataset | Dates | records | no_records | denied | failed | Workflow run |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `sedentary-period` | Oct 3–9 | 7 | 0 | 0 | 0 | [38148633616](https://github.com/han33-dotcom/Sentra/actions/runs/38148633616) |
| `respiratory-rate-sleep-summary` | Oct 3–9 | 6 | 1 | 0 | 0 | [38148789760](https://github.com/han33-dotcom/Sentra/actions/runs/38148789760) |
| `activity-level` | Oct 9 only | 1 | 0 | 0 | 0 | [38148966963](https://github.com/han33-dotcom/Sentra/actions/runs/38148966963) |

- Respiratory October 9 returned `no_records`. The respiratory responses deduplicated
  to one stored record: job outcomes and unique record counts measure different
  things.
- Outcomes count requested jobs and pages, not proof of complete measurements.
- **Activity October 3–8 is deferred.** Six days like October 9 would add about
  137 MB. Only about 70 MB remained before the 380 MB import limit (database
  310.2 MB).

### Measured storage per dataset

From `sentra shared-growth` after the probe. Decimal bytes; the database estimate
applies the project-wide allocation ratio and is not a forecast.

| Dataset | Requested days | Unique records | Measurements | Payload bytes | ≈ database bytes per requested day |
| --- | ---: | ---: | ---: | ---: | ---: |
| `sedentary-period` | 7 | 133 | 1,840 | 2,066,471 | 450,688 |
| `respiratory-rate-sleep-summary` | 7 | 1 | 12 | 10,871 | 2,371 |
| `activity-level` | 1 | 907 | 13,461 | 14,995,759 | 22,893,574 |

The pre-probe estimate for `activity-level` (0.4–2.3 MB per participant-day)
was about 10× too low. Each interval becomes about 15 measurement rows, mostly
timing fields. A storage reduction plan should consider these options before any
further collection:
- keep the dataset out of `audit.measurements` and store it only in originals and
  parquet tiers;
- store a compact daily representation;
- or drop the dataset, since processing does not use it.

If daily collection is re-enabled for a dataset without any coverage yet, the
planner reports a `failed` outcome ("No initial coverage") instead of backfilling
silently.
