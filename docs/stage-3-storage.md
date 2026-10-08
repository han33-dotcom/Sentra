# Stage 3 — private shared storage

Implemented on `ETL-pipeline`, 8 October 2026. No branch change, paid service,
commit or push was made. Both participants' recorded agreement settings were
checked before transferring the existing Stage 2 imports.

## Operational scope

The [Sentra project](https://supabase.com/dashboard/project/jpweubkzwbjvydwblfmm)
is in the Sentra **Free** organization, Frankfurt region, Nano compute.
PostgreSQL stores searchable audit records and collection state. The private
`sentra-originals` bucket stores gzip-compressed unchanged responses; hashes
verify original byte identity after decompression. Cloud originals use private
platform storage; local originals/backups are additionally encrypted.

Separate collector/viewer database logins and allowlisted Storage service
accounts restrict writes and credentials. Connections verify the database
certificate, and SSL enforcement is enabled server-side. Anonymous originals
are inaccessible. Dashboard administrators retain privileged access; limit
administrative membership to authorized operators.

Transfers resume safely, deduplicate immutable originals, update corrected
records atomically and save coverage after durable data. Shared and local writer
locks prevent concurrent operations. Provider OAuth tokens **remain local**;
no daily workflow, browser viewer or viewer credential distribution was added.

## Review and try

Read [schema review](schema.md), [foundation SQL](../sql/001_foundation.sql) and
[permissions SQL](../sql/002_permissions.sql). Code is in `src/sentra/shared*.py`
and `recovery.py`; tests use synthetic fixtures only. Real imports/credentials
remain ignored under `.private`.

From the repository root in PowerShell:

```powershell
.venv\Scripts\sentra.exe --config config/local.toml shared-status
.venv\Scripts\sentra.exe --config config/local.toml shared-growth
.venv\Scripts\sentra.exe --config config/local.toml shared-check-access
.venv\Scripts\sentra.exe --config config/local.toml shared-sync all
.venv\Scripts\sentra.exe --config config/local.toml shared-verify all --originals
```

Sync uploads the durable local import without new provider requests. Verification
compares counts, local/remote hashes, full remote record JSON and searchable
scalar/session contents; `--originals` also downloads/hashes each unique response.
Verification and downloads consume egress.

## Reproduce account setup

The current project is already configured. For a replacement Free project:

1. Create only a Free organization/project with an operator-chosen database password. Disable automatic new-table API exposure and enable SSL enforcement.
2. Install using Stage 1 instructions (`requirements-windows.txt` on Windows). Initialize or recover the OS encryption key as appropriate.
3. Copy `config/supabase-admin.example.json` to ignored `.private/supabase-admin.json`. Fill project URL, publishable/secret keys and exact **session** pooler host/port/admin username/password from the dashboard. Never put values in chat, Git or logs.
4. Save the official certificate offered by Database Settings as `.private/supabase-ca.crt`. Use session pooling; transaction pooling does not preserve advisory locks.
5. Confirm organization billing says Free and set admin-file and `[shared]` `confirmed_free_plan` flags. Copy shared thresholds from `config/example.toml` to ignored `config/local.toml`.
6. Check organization uncached-egress usage, choose an upper bound in bytes allowing for dashboard rounding/delay, then run `shared-bootstrap --egress-baseline-bytes NUMBER` with the executable/config prefix above. It deploys versioned SQL and encrypts restricted runtime credentials in `.private/shared`. Repetition resumes setup; changed installed SQL requires a reviewed new migration.

Before replacing a project, preserve prior encrypted setup/collector/viewer files
in a separate private archive. The setup journal refuses silent project replacement.
Bootstrap secrets in the ignored admin JSON are plaintext: restrict them with OS
account permissions. Runtime bundles use the OS-held encryption key. Future
viewer deployment receives only its own read-only credentials through hosting
secrets, **never** the OS key, collector/admin bundles or whole private directory.
That OS key also decrypts local OAuth credentials.

## Zero spending and capacity

Supabase [pricing](https://supabase.com/pricing), checked 8 October 2026, lists
Free 500 MB database, 1 GB objects, 5 GB uncached and a separate 5 GB cached
egress allowance, with no automatic backups. The spend-cap switch belongs to
Pro; [official cost controls](https://supabase.com/docs/guides/platform/cost-control)
state that Free usage is not charged. Keep the organization on Free, without
paid add-ons or upgrades. Quotas are not unlimited capacity.

| Guard | Ceiling | Additional reserve |
| --- | ---: | ---: |
| Database | 350,000,000 bytes | 20,000,000 plus estimated next batch |
| Objects | 700,000,000 bytes | 20,000,000 plus next object |
| Monthly uncached egress | 3,500,000,000 bytes | Conservative reservations before reads |
| Local private workspace/backups | 200,000,000 bytes | Free-disk checks and serialized writes |

Database/object guards measure this project, including non-audit database size
and all its buckets. Organization fair-use averages/dashboard metrics may differ
or lag. This organization has one project; adding another or using external
database/download clients requires review of organization allowances. The
application cannot meter unrelated clients.

`egress_bytes` is a **verified baseline plus reserved usage**, not a billing meter.
Reservations are conservative, never refunded or reduced. Initial verified usage
was buffered to 20 MB. At least weekly and at each new UTC month, check organization
usage and run `shared-budget --egress-baseline-bytes NUMBER` using a verified
upper bound. Baselines expire after seven days; a missing new-month baseline
stops operations. Do not assume zero usage. Unknown required usage fails closed.

Stops preserve completed data and earlier progress; nothing automatically deletes,
downsamples or upgrades. Address the reported cause and repeat the command.

## Import and growth finding

| Provider | Records | Scalar measurements | Sessions | Fetch manifests | Unique originals |
| --- | ---: | ---: | ---: | ---: | ---: |
| Google Health / Fitbit | 61,656 | 138,141 | 37 | 286 | 156 |
| WHOOP | 137 | 2,586 | 107 | 8 | 8 |

Requested ranges remain the Stage 2 daily/session 30 days, Google minutes seven
days and one representative original-resolution heart-rate day. WHOOP sessions
include cycles. Import success is not proof of complete measurements or accuracy.

After numeric precision repair and the small restoration, measured database size
was **268.7 MB**, including **255.3 MB** in audit tables/indexes. Unique compressed originals total
**655,605 bytes** (Google 640,915; WHOOP 14,690). Fresh status includes later tests
and restoration allocation.

Growth output reports measured payload sizes and means per requested day with a
project-wide table/index overhead adjustment. Minute datasets total about
**17.3 MB per requested day**, WHOOP about **0.083 MB/day**. The representative
original-resolution day accounts for approximately **121.8 MB** allocated in the
database; it is not planned as a daily request. Missing days/corrections influence
means. These are initial-import estimates, not longitudinal forecasts; newer
lossless context compaction may reduce future rows.

About 61 MB remains below the effective 330 MB guard. The user approved a
[three-day initial observation](stage-7-audit-plan.md), replacing the proposed
two weeks while retaining existing imports. Three days of minute data alone
would add roughly 52 MB, approaching 321 MB total before other datasets and
correction/test overhead. **Three days are not guaranteed to fit.** Before
scheduling/start approval, recheck actual growth, current usage and projected
batches. If needed, review lossless representation improvements or an explicitly
agreed scope change. Keep safe stops; do not silently discard fields/delete
history, raise free quotas or buy capacity. No stack change was made.

An actual Google sleep batch stopped on its conservative size estimate. Lossless
common-context reuse reduced the estimate; 26 outstanding records resumed with
all fields preserved. Numeric inserts now use exact decimal text; versioned
`003_numeric_precision.sql` repaired float-cast rounding in searchable values
from the preserved record JSON. Responses, records and their hashes were unchanged.
Final fresh-process comparisons passed for all counts, JSON and searchable values,
and all 164 unique originals. Repeating sync changed zero records or manifests.
The synthetic suite passed 56 tests with two cloud tests skipped; those two were
separately enabled and passed using rolled-back synthetic transactions. Permissions,
capacity stops, corruption detection, correction/removal and restoration checks
passed. Dependency, compilation, SQL parsing and independent review passed.
See the execution ledger for details.

## Manual backup and restoration

```powershell
# Complete health workspace, or a selected rehearsal:
.venv\Scripts\sentra.exe --config config/local.toml shared-backup
.venv\Scripts\sentra.exe --config config/local.toml shared-backup --participant p02 --provider whoop --dataset sleep
# Use the printed manifest path; preserve the whole containing folder:
.venv\Scripts\sentra.exe --config config/local.toml shared-restore .private/backups/BACKUP_ID/manifest.enc
```

Backups take a coherent snapshot, stream encrypted bounded chunks, include selected
source originals, and authenticate hashes/counts/row fingerprints. They exclude
OAuth credentials, database passwords, Storage accounts and keys. An unfinished
folder without a final manifest is not a completed backup. Keep completed folders
in an existing private off-machine location restricted to authorized operators;
a laptop-only copy does not protect against losing the laptop.

Protect the OS-held key using an operator-chosen passphrase:

```powershell
.venv\Scripts\sentra.exe save-recovery-key .private/recovery/local-key.json
# Replacement OS account, before generating another vault key:
.venv\Scripts\sentra.exe recover-key .private/recovery/local-key.json
```

Prompts hide the passphrase. Keep envelope and passphrase separately; never make
the envelope a viewer download. Recovery refuses to overwrite a different OS key.
Wrapping/wrong-passphrase/corruption checks were synthetic; an actual off-machine
recovery has not been done. The operator still needs to save the recovery copy.

Default restoration creates a new admin-only `sentra_restore_*` schema, validates
counts/row fingerprints and restores/verifies immutable originals. Operational
tables stay intact. Rehearsal tables consume quota; inspect before approving cleanup.
For an initialized replacement project whose **seven audit tables are all empty**,
add `--empty-audit` to restore operationally with deployed policies/foreign keys.
It refuses existing data. Original uploads preceding a later restoration failure
remain private, count toward usage and are not deleted. New empty-project disaster
recovery has not been exercised.

The real rehearsal restored 30 WHOOP sleep records/sessions, 780 measurements,
two manifests, one participant/state and six collection-run records into
`sentra_restore_66afba6cc893`, with matching fingerprints and verified originals.
This was run in a fresh CLI process. The full-workspace backup command is available;
only this selected real backup/restoration has been demonstrated.

Supabase's [backup guide](https://supabase.com/docs/guides/platform/backups)
recommends off-site exports on Free and notes that database backups exclude
Storage objects. Sentra's backup includes selected audit data and objects; Git
SQL/bootstrap recreates permissions separately.

## Pausing and stage boundaries

Free projects with too little database activity over a week may pause. Watch
owner emails, resume through the dashboard and retry. The [current pause guide](https://supabase.com/docs/guides/platform/free-project-pausing)
allows dashboard resumption for up to one year. Keep backups; do not rely on
indefinite retention or upgrade to prevent pausing. No extra keep-alive collection
or polling was added.

Stage 4 will move background authorization/state to cloud operation, schedule one
daily midnight Asia/Beirut workflow, recover/recheck intervals and isolate provider
failures. Plan for the approved three-day observation window and a pause pending
review at its end. First verify capacity and baseline renewal; Google Testing-mode reconnects
still apply. Stage 5 will deliver the private teammate browser and downloads.
Neither stage has started. Final checks are recorded in [the ledger](stage-3-plan.md).
