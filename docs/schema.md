# Audit schema review — deployed in Stage 3

The PostgreSQL definition is in [001_foundation.sql](../sql/001_foundation.sql).
It was deployed on 8 October 2026, together with [002_permissions.sql](../sql/002_permissions.sql).
Forced row-level security and restricted roles/private Storage policies are active.
See [Stage 3 operations](stage-3-storage.md) for setup, evidence and remaining boundaries.

| Storage | Purpose and important fields |
| --- | --- |
| `audit.participants` | Stable pseudonyms such as `p01`, `p02`; no names, emails or vendor account IDs |
| `audit.records` | Stable provider/dataset record key, complete normalized/vendor context, content hash and original-response reference; parent context can be shared losslessly across metric JSON |
| `audit.measurements` | Participant/provider/dataset/metric, standardized value/unit, vendor value/unit, point time or interval, vendor time, collection time, resolution, classification and source pointer; vendor metric paths also remain in record JSON |
| `audit.sessions` | Sleep/workout/cycle record keys, interval, score state and provisional flag; join `records` for complete vendor fields, provider IDs and source reference |
| `audit.raw_response_manifest` | Endpoint, requested range/resolution, collection time, private object location, hash of unchanged response bytes and compressed size |
| `audit.collection_runs` | Participant/provider run status and full durable local context: requested/stored intervals, counts, sanitized failures and local storage statistics |
| `audit.connection_state` | Authorization status plus successful stored progress, continuation cursor and coverage separately for every dataset |
| `collector_private.provider_credentials` | Reserved encrypted token storage, inaccessible to the viewer; **empty in Stage 3**, with provider authorization remaining local until Stage 4 |

Values carry an explicit `value_kind`: measurement, vendor calculation, vendor
summary, vendor score, Sentra calculation or unknown. Choosing a category needs
provider documentation/evidence. A heart-rate API point is not automatically a
physical sensor signal. A future derived value needs a calculation/version
reference. Stage 2 normalizes selected fields, preserving vendor paths and units;
there are no derived indicators or health scores.

Standardized values can be null when a value is not numeric or conversion is not
established. Preserve vendor values/units and retain unknown fields in original
responses/session JSON. Never infer a zero from a missing value.

Measurements may have an instant, a positive interval, a civil date or explicitly unknown time. UTC timestamps retain
the original vendor time/offset/civil date separately; a calendar day must use
its actual timezone boundaries. Unknown resolution remains explicitly unknown.
WHOOP cycles are intervals, not midnight-to-midnight daily records.

The unique measurement key combines participant/provider/dataset/metric with a
stable vendor source-record key and sample key. Sessions use the vendor session
ID within participant/provider/dataset. Atomic upserts replace the record and its
metric/session projections, including removal of obsolete metrics. Do not use collection time or random UUIDs as deduplication keys.
When a source has no ID, Stage 2 documents a deterministic identity based on
the dataset's semantics, excluding mutable values.

Manifest entries describe each fetch, even if unchanged content reuses the same
object by hash. Equal content from different participants must not be shared
across access boundaries. A changed payload receives another object/hash; the
normalized row then points to its new source. Original responses are API output,
including vendor summaries/scores, not unprocessed sensor signals.

Availability labels preserve missing, unsupported, unscored, provisional,
failed-to-fetch and unknown states where evidence supports them. Missing records
cannot be materialized as timestamped measurements without a justified expected
interval; use collection/coverage evidence instead. A successful fetch does not
establish complete coverage.

Covered intervals advance only after objects, manifests and normalized data are durably saved. They are neither
the newest measurement timestamp nor proof of completeness. Recent data stays
provisional. Provider failures do not advance another dataset's progress.

Stage 3 enforces viewer roles, private object policies, usage reservations and quota
guards, and health-data restoration. `collector_private.storage_members` stores the
private service-account allowlist; `egress_budget` stores verified monthly baselines
and conservative transfer reservations; `schema_versions` tracks applied SQL hashes.
The viewer can read audit data/private originals, but cannot write either, read
provider credentials or assume the collector role. Dashboard administrators retain
privileged access and should be limited to authorized operators.
`last_success_at` reflects underlying successful collection, not present authorization
or complete measurement availability. Cloud OAuth renewal/scheduling and teammate
browser authentication remain Stages 4/5.
