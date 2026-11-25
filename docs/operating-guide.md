# Sentra operating guide

For the authorized university team. See the [November sprint closeout](sprint-closeout.md) for verified participant counts and the last dashboard publication. Keep individual records, downloads, credentials and
consent details private. Vendor summaries and scores are not diagnoses or raw
physical sensor signals. No AI model or health-risk score is implemented.

## Start here

The [private viewer](https://sentra-wearable-audit.streamlit.app) uses
`viewer/app.py` and Python 3.11. The existing host is configured for `ETL-pipeline`;
that deployment reference must exist while the host uses it. See the
[dashboard restoration runbook](dashboard-restoration.md) for the verified
configuration and recovery evidence. Sign in with an approved Google account,
choose participant/provider and Beirut dates, then **Load selected data**.
The initial dates select the latest
available measurement week for that participant/provider. **Latest available week**
returns to that period; **Last 7 calendar days** selects the trailing seven calendar days.
Manual dates survive navigation through the Wellness board. Measurement dates
come from returned records, not the time of a successful fetch or board publication.
The displayed end date is included. Use sidebar search for export filtering;
table search/sort only changes the display. Daily activity has one row per day;
Sleep and Workouts have one row per session. Sleep uses its Beirut wake date;
workouts use their start date. WHOOP recovery attaches only by vendor sleep ID.
Missing values stay missing, and multiple-source values are not silently merged.

**Prepare readable CSV** exports labelled values with exact source values, units,
classification and provenance for the overview dates. **Audit details** retains
dataset/metric/search filters, full record context, unmapped paths and original
responses. Choose **Load audit details** to prepare the detailed selection.

**Prepare filtered CSV** then its Download link saves all matching rows, with
vendor values, units, timing and source references. Narrow filters if the selection
exceeds 10,000 rows or 20 MB. **Original responses → Prepare original response**
downloads the unchanged compressed source page, including other returned fields
and dates on that page. Its manifest states requested resolution/range. A minute
rollup is an aggregated API response, not original sensor resolution.

Refresh explicitly for new data. Filter changes clear results/downloads. An expired
identity needs sign-out/in. If Community Cloud has hibernated, an authorized viewer
can wake it; the collector is independent. Save downloads in a private location.
The application's approved email list remains required even if someone receives
another platform invitation. Operators remove access through managed viewer
secrets and restart; previously downloaded files cannot be recalled.

## Operator setup

Before resuming the paused collector, use the current
[collection restart readiness ledger](collection-restart-readiness.md) for #44.
`sentra cloud-readiness` inspects stored authorization/capacity without provider
calls and saves encrypted private evidence; it never authorizes or enables a run.
Historical stage acceptance and the zero-spend variable do not replace fresh
readiness checks, agreed windows and restart authorization.

Use an existing authorized checkout and Python 3.11. Follow [Stage 1](stage-1-setup.md)
for the local environment/OS vault, [Stage 3](stage-3-storage.md) for restricted
Supabase configuration and [Stage 4](stage-4-collection.md) for cloud credential
ownership and GitHub secrets. Follow [Stage 5](stage-5-viewer.md) for the separate
identity client and viewer-only managed secrets. A new operator needs secure
key/configuration recovery or participant reauthorization; cloning Git alone
cannot access credentials. Never copy the whole `.private` folder to Streamlit.

Commands below run from the repository root in PowerShell with the prepared
`.venv` and ignored `config/local.toml`. Linux uses `.venv/bin/sentra` instead.
Health downloads/backups must remain ignored; do not enable OAuth/HTTP debug logs.

## Manual runs and reconnect

Open [GitHub Actions](https://github.com/han33-dotcom/Sentra/actions) →
**Private wearable collection → Run workflow**. Select the reviewed branch,
`recovery`, one provider/dataset and explicit dates. Collector `end` is exclusive,
unlike the viewer's included end date. Manual windows cover 1–30 past Beirut days,
with end no later than today. `initial` uses the bounded initial scope; do not
repeat a whole-history import merely to fix one dataset.

For a one-participant verification, prefer the local launcher and pass the privately
selected participant ID explicitly. The example below uses a placeholder; without
this filter, the runtime can select multiple connections. Agree the dates, current
consent and exact scope before any run. The collector still applies its existing
capacity, token and date checks. Store the output privately.

```powershell
.venv/Scripts/sentra.exe cloud-run-local --mode recovery --provider google_health --participant YOUR_PRIVATE_ID --start 2026-10-07 --end 2026-10-08 --dataset daily_steps
.venv/Scripts/sentra.exe cloud-run-local --mode recovery --provider whoop --participant YOUR_PRIVATE_ID --start 2026-10-07 --end 2026-10-08 --dataset sleep
.venv/Scripts/sentra.exe shared-status
```

Repeating a recovery safely revisits records; rerunning the same GitHub execution
skips its completed jobs. Stored coverage recovers missed intervals. Retries remain
inside the run; do not add polling/webhooks. An older-than-30-day recovery requires
a separately bounded manual import. Inspect provider/dataset failures even when
another provider succeeded. If a writer/refresh is busy, let it finish and repeat;
never force overlapping token rotations.

For revoked/expired authorization or an interrupted/ambiguous refresh:

```powershell
.venv/Scripts/sentra.exe cloud-connect google_health --reauthorize
.venv/Scripts/sentra.exe cloud-connect whoop --reauthorize
```

Run only the affected command. That participant completes browser consent on the
callback computer; retain the existing read-only scopes. Google collector Testing
tokens expire after seven days; refreshing an access token does not restart that
period. WHOOP replaces its refresh token on renewal. Both replacements are stored
under cloud locks before further requests. An uncertain rotation stops for
reconnect rather than retrying an invalidated token. Do not use local `refresh`,
`authorize`, `sample` or `initial-import` on cloud-owned token copies.
See [Google expiry](https://developers.google.com/identity/protocols/oauth2#expiration)
and [WHOOP renewal](https://developer.whoop.com/docs/developing/oauth/).

## Read failures and capacity

| Evidence/status | Operator action |
| --- | --- |
| Succeeded coverage, sparse measurements | Inspect returned fields and sync/wear history; stored pages do not prove complete sensor readings. |
| Missing/unsupported/unscored/provisional | Respect the label's evidence; no rows alone do not prove unsupported. Recent sleep may still be in progress. |
| Failed/partial fetch | Inspect dataset status and repeat bounded recovery after addressing the reported cause. Earlier durable pages remain. |
| Reconnect required | Use the affected cloud reconnect command; never print tokens or provider error bodies. |
| Capacity stop or unavailable/stale budget | Check organization usage and the next batch size; preserve data and thresholds. |
| Viewer database unavailable | Check project pause, connection/certificate and viewer-only secrets. Check the project state in the signed-in dashboard. |
| Streamlit says no access or app does not exist | Sign in to the deployment account at share.streamlit.io. Confirm the app, branch and entrypoint before changing sharing. This message alone does not establish that the app was deleted. |
| Streamlit source download fails / main module does not exist | Check that the configured Git branch exists. Preserve the existing private app, secrets and URL; see the restoration runbook before replacing a deployment. |

```powershell
.venv/Scripts/sentra.exe shared-growth
.venv/Scripts/sentra.exe shared-check-access
# Only after checking organization uncached egress in the dashboard:
.venv/Scripts/sentra.exe shared-budget --egress-baseline-bytes VERIFIED_UPPER_BOUND
```

The database ceiling is 400 MB with 20 MB reserved: imports stop before 380 MB
plus the estimated next batch. Objects use 700 MB with 20 MB reserved. Monthly
uncached egress is capped internally at 4.5 GB (owner-approved November 18, 2026).
These are decimal MB/GB. Egress
is a verified baseline plus conservative reservations, not a billing meter;
reservations are retained after failures. Verify the baseline at least weekly
and at each new UTC month. Unknown/stale usage stops operations. Read/download
checks also consume allowance. Do not reset reservations, silently delete history,
raise quotas, upgrade plans or add paid runners.

The owner retained Supabase Pro with no additional spend. The software still requires the legacy configuration field
`confirmed_free_plan`. Keep the 4.5 GB stop and GitHub's account-wide Actions **$0 budget / Stop usage:
Yes**. Recheck their dashboards before enabling collection; account-wide allowances are
shared with other projects. Initial-import growth averages are approximate and
include gaps/index overhead. They do not promise ongoing capacity.

## Backup and recovery

See the [service account handoff](service-account-handoff.md) for service
administration, contacts and access recovery.

```powershell
# Complete health workspace; selected rehearsal can add participant/provider/dataset:
.venv/Scripts/sentra.exe shared-backup
# Preserve the whole printed backup folder, then validate in an isolated private schema:
.venv/Scripts/sentra.exe shared-restore .private/backups/BACKUP_ID/manifest.enc
.venv/Scripts/sentra.exe save-recovery-key .private/recovery/local-key.json
```

Keep completed encrypted backups, encrypted operator setup bundles and the
passphrase-protected OS-key recovery envelope in an existing private off-machine
location. Keep the passphrase separate. The backup's final `manifest.enc` and
whole containing folder are required; unfinished folders are not complete backups.
Health backups include originals and seven audit tables, **exclude credentials**,
and do not include private daily-job checkpoints, quota/control tables or cloud
keys. Preserve `.private/cloud/setup.enc` and authorization/configuration bundles
separately; otherwise reauthorize participants and rebuild bounded recovery state.
Provider rotation history is not recoverable from an old local token snapshot.

Default restore leaves operational tables intact and verifies a new admin-only
`sentra_restore_*` schema. It consumes database quota; review rehearsal retention
before further restores. `--empty-audit` is for an initialized replacement project
whose seven audit tables are all empty; it refuses populated targets and requires
`--target-project <ref>` naming the configured project before writing (see
[recovery-rehearsal.md](recovery-rehearsal.md)). Recreate
migrations/permissions/configuration and reconnect before operating a replacement.
A full new-project disaster recovery and off-machine key recovery have not been
demonstrated. Keep verified application backups, including original objects; [Supabase's backup guide](https://supabase.com/docs/guides/platform/backups)
also explains that database backups alone exclude Storage objects.

## Observation approval and documentation

On 10 October the human deferred ongoing collection and approved a bounded
October 7–9 backfill for both participants, with a 400 MB database ceiling and
20 MB reserve. Both automatic collection controls remain paused. Continuous
collection and scaling require a later decision after researching project use
cases. Compare requested coverage with returned measurements; a completed
request does not prove uninterrupted data. Last-day late data may remain pending; no extra run
is automatic. To stop, set `SENTRA_COLLECTION_ENABLED=false` in GitHub and run
`cloud-window --pause`. Ongoing SQL control has no automatic end date; quota and
authorization stops remain mandatory. Record actual enabling time and the first
successful approved run before calling it operational.

Keep the viewer link with restricted team operating materials. Use the
[data dictionary](data-dictionary.md) for metric definitions.
Document definitions, vendor classification, units, sampling, source IDs and
observed gaps/delays. Keep findings preliminary; two different devices cannot
validate general accuracy or health predictions. [Stage 6 evidence](stage-6-validation.md)
states the exact demonstrated scope and pending checks.

## November pilot collection scope

The completed sprint verified ten distinct consenting contributors with usable recent data,
five WHOOP and five Fitbit. Count enrollment, connected accounts, usable recent
coverage and assessment readiness separately for each provider. Count a person
wearing both devices only once toward ten. Record aggregate evidence on SEN-38,
SEN-47, SEN-43 and SEN-50. Use approved private pilot records for reconciliation.

For scheduled GitHub runs, set the private repository secret
`SENTRA_SCHEDULE_SCOPE` to a JSON list before requesting restart approval.
Each entry names exactly one configured or discovered connection and a nonempty
list of daily datasets. For example, these **synthetic** entries show the format:

```json
[
  {"participant":"p901","provider":"google_health","datasets":["daily_steps","sleep","daily-resting-heart-rate","daily-heart-rate-variability"]},
  {"participant":"p902","provider":"whoop","datasets":["cycle","sleep","recovery"]}
]
```

Keep the actual secret and account IDs private. A missing, empty or invalid
scope stops the scheduled run before any provider request. Additional enrolled
accounts need a separately approved scope update. Initial and recovery imports
use the existing bounded manual procedure. The scope does not grant consent,
establish initial coverage, change correction dates or activate either control.
With the same private scope in the local environment, run
`sentra cloud-run-local --preview-schedule YYYY-MM-DD` for the intended Beirut
run date. This reserves transfer for bounded metadata reads and prints planned
datasets, dates and any planning failures. Verify consent, credentials and
headroom, then obtain the operator decision for the specific dates and budget.

For an approved three-day, single-connection pilot, keep the same private
scope in the launcher environment and use `sentra cloud-window --start
YYYY-MM-DD --approved --pilot-mb N` with the approved decimal MB allowance.
The SQL control binds the account and datasets, pins the current ledger month
and adds the allowance to the current shared transfer reading. Other shared
usage consumes this headroom too. The collector claims each Beirut day once
and opens the next day only after recording success. A crash leaves the day
claimed for operator inspection. The third successful cycle pauses SQL.
Inspect the receipts and turn the GitHub schedule switch off at closeout.

### Resuming a local stored-data refresh

The incremental builder compares source fingerprints per month for measurements,
sessions, and the two heart-rate inputs together. Corrections and removals
invalidate the affected group. The hot retention cutoff still applies to reused
heart-rate files.

For an approved local run, `--checkpoint-dir` on `python -m sentra.wellness_refresh`
keeps authenticated, encrypted pages and completed derived groups in a private
operator directory. It uses the existing OS credential store. An interrupted
read resumes against a fresh source fingerprint. Keep the same project, code,
checkpoint directory and absolute transfer ceiling on retry. Handle checkpoint
files as private participant data under the existing retention policy.

The bounded operator can pass a sized source inventory and expected published
hashes to `RefreshCheckpoint`, and `finish_allowance` to `refresh` to keep
transfer available for publishing and independent verification. All reads and
writes still use the shared transfer ledger. A stopped run grants no new
allowance.
