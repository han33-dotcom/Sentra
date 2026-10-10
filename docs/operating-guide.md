# Sentra operating guide

For the consented university team. Current participants are `p01` (Google Health /
Fitbit Air) and `p02` (WHOOP). Keep individual records, downloads, credentials and
consent details private. Vendor summaries and scores are not diagnoses or raw
physical sensor signals. No AI model or health-risk score is implemented.

## Start here

The [private viewer](https://sentra-wearable-audit.streamlit.app) runs from
`ETL-pipeline`, `viewer/app.py`. Sign in with an approved Google account, choose
participant/provider and Beirut dates, then **Load selected data**.
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

Equivalent fresh-process local recheck of an already imported day:

```powershell
.venv/Scripts/sentra.exe cloud-run-local --mode recovery --provider google_health --start 2026-10-07 --end 2026-10-08 --dataset daily_steps
.venv/Scripts/sentra.exe cloud-run-local --mode recovery --provider whoop --start 2026-10-07 --end 2026-10-08 --dataset sleep
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
| Viewer database unavailable | Check project pause, connection/certificate and viewer-only secrets. Resume a paused Free project through its dashboard. |

```powershell
.venv/Scripts/sentra.exe shared-growth
.venv/Scripts/sentra.exe shared-check-access
# Only after checking organization uncached egress in the dashboard:
.venv/Scripts/sentra.exe shared-budget --egress-baseline-bytes VERIFIED_UPPER_BOUND
```

The database ceiling is 400 MB with 20 MB reserved: imports stop before 380 MB
plus the estimated next batch. Objects use 700 MB with 20 MB reserved. Monthly
uncached egress is capped internally at 3.5 GB. These are decimal MB/GB. Egress
is a verified baseline plus conservative reservations, not a billing meter;
reservations are retained after failures. Verify the baseline at least weekly
and at each new UTC month. Unknown/stale usage stops operations. Read/download
checks also consume allowance. Do not reset reservations, silently delete history,
raise quotas, upgrade plans or add paid runners.

Keep Supabase on Free and GitHub's account-wide Actions **$0 budget / Stop usage:
Yes**. Recheck their dashboards before enabling collection; account-wide allowances are
shared with other projects. Initial-import growth averages are approximate and
include gaps/index overhead. They do not promise ongoing capacity.

## Backup and recovery

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
whose seven audit tables are all empty; it refuses populated targets. Recreate
migrations/permissions/configuration and reconnect before operating a replacement.
A full new-project disaster recovery and off-machine key recovery have not been
demonstrated. Free hosting needs manual backups; [Supabase's backup guide](https://supabase.com/docs/guides/platform/backups)
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

Link the viewer and [data dictionary](data-dictionary.md) from private Notion.
Document definitions, vendor classification, units, sampling, source IDs and
observed gaps/delays. Keep findings preliminary; two different devices cannot
validate general accuracy or health predictions. [Stage 6 evidence](stage-6-validation.md)
states the exact demonstrated scope and pending checks.
