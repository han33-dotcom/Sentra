# Stage 7 — three-day initial audit plan

Decision updated on 8 October 2026: the user approved a **three-day initial
observation period** in place of the originally proposed two weeks, to limit
additional storage. Findings will be preliminary. This changes observation
duration, not the history already imported or the selected datasets/resolutions.

## Start and collection boundaries

- Complete and review Stages 4–6 first. Start this period only after explicit approval to begin Stage 7; approval of this plan does not start collection or the observation clock.
- Observe three full days. Record the actual approved start/end timestamps in UTC and Asia/Beirut when the period begins; no start/end date is assigned yet.
- Use the normal once-daily run at 00:00 Asia/Beirut, including its approved missing-interval recovery and previous-three-day correction checks. No extra polling, webhooks or increased frequency.
- Plan to pause further collection at the end of the approved window pending review. An extension requires explicit approval and a fresh capacity check. A three-day pilot is not a rolling three-day retention policy.
- Retain existing imports and originals. Do not delete older history or silently drop returned fields to fit the pilot.
- Record actual run times, delayed/missed runs and recovery outcomes. Three elapsed days do not establish three successful runs. If capacity or authorization prevents completion, report the shortened observation and blocker honestly.

## Capacity gate

Stage 3 measured approximately 268.7 MB of database storage, with an effective
330 MB guard after the configured reserve. Initial minute-data allocation
averages about 17.3 MB per requested day; three additional days would contribute
roughly 52 MB, bringing the database to approximately 321 MB **before** other
datasets, correction overhead and further test/backup/restoration allocation.
This estimate leaves little headroom and does not guarantee three days will fit.

Before starting, measure current usage and account for intervening Stage 4–6
validation, all selected datasets and projected batches. Keep existing guards
and zero-spending controls. Stop safely if capacity is insufficient; review a
lossless representation improvement or explicitly agreed scope change. Do not
automatically raise quotas, delete data or upgrade services.

See [Stage 3 capacity and operating instructions](stage-3-storage.md).

## Audit inventory and acceptance

Use the three-day window plus the retained initial history, clearly distinguishing
historical imports from data actually observed arriving during the pilot.

| Audit item | Evidence to record |
| --- | --- |
| Available/unavailable fields | Endpoint, returned fields, unsupported/missing/unscored/failed states supported by evidence |
| Meaning and classification | Vendor definitions, units; measurements versus vendor calculations, summaries and scores |
| History and resolution | Requested/returned intervals, observed sampling, aggregation and original-resolution labels |
| Coverage and corrections | Gaps, changed records, missing intervals, provisional records and failure/recovery status |
| Delivery delay | Measurement/session time, first observed arrival and subsequent corrections; once-daily collection bounds rather than precise vendor delivery times |
| Storage | Actual database/object growth, conservative egress reservations, remaining capacity and stops |
| Candidate features | Indicators supported by returned fields, required assumptions and missing inputs; no model or health-risk scoring |
| Limitations | Short observation, two participants with different devices, unobserved intermittent/weekly behavior and unresolved late corrections |

Acceptance requires three full elapsed days, an evidence-based inventory, actual
execution/coverage/capacity outcomes and a clear operational/blocked status. If
the period has not elapsed, provide the inventory template with findings pending;
do not mark Stage 7 complete. Final-day sleep and other recent records may remain
provisional; do not add unscheduled requests or claim they are finalized.

The pilot establishes initial extraction/audit behavior. It cannot establish
general device accuracy, validate health predictions, or characterize weekday/
weekend and intermittent behavior reliably. Longer observation is optional after
review and sufficient capacity. Link the inventory/data dictionary and findings
from private Notion documentation without exposing health data or download links.

**Current status:** planned; observation has not started and findings are pending.
