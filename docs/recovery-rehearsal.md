# Recovery rehearsal (#30)

Status: **hosted full recovery verified November 18, 2026 (Beirut).** Repeat only under
an explicit operator scope after a verified backup ([retention-policy.md](retention-policy.md))
and before any destructive storage step (#46). Record the results table below in the task,
never the backup itself. NIST SP 800-34 treats restoring from backup media as part of
contingency testing (see [retention-evidence.md](retention-evidence.md), reference 16).

## Where to restore

**Not into the live project.** `shared-restore` without `--empty-audit` creates an isolated
`sentra_restore_*` schema in the *same* database, which doubles the data. That cannot fit beside
the live data under the 400 MB database guard, and it would compete with collection headroom anyway.

**Size check.** Before writing, the restore asks the capacity guard for the source's measured
table sizes (recorded in the backup manifest as `table_bytes`, including indexes) × 1.05 + 16 MB.
`shared-backup-verify` prints this as `restore_estimate_bytes`. While rows are inserted, the guard
is rechecked after every ~1 MB of input, so the restore stops and rolls back before any limit is
crossed. Backups taken before `table_bytes` existed fall back to their serialized size, which is
larger than the real storage: take a fresh backup before a full rehearsal. A full restore fits in an
empty Free project only while the live audit tables plus this margin stay below the guard. Compare
`restore_estimate_bytes` with the target's `shared-status` first.

Rows are submitted with Psycopg `executemany()` once per bounded encrypted chunk.
This avoids waiting for a separate cloud round trip for every row. The same outer
transaction, capacity checkpoints, table fingerprints and identity-sequence
rollback apply. A constraint failure within a chunk must roll back earlier rows
and allocator changes; the real-PostgreSQL regression suite checks this.

Organization egress is shared across its projects. If the live organization's
remaining allowance cannot cover recovery, use a separately verified Free
organization within the account's Free project limit. Establish a conservative
baseline for that organization; never reset the live ledger or assume a new
project in the same organization has a fresh allowance.

Use a **separate, throwaway Supabase Free project** and a **separate checkout** for it. A
different `--config` file name in the live checkout is not enough: `load_connection()` and
`read_shared()` take the database and storage credentials from that checkout's own `.private`
(`.private/shared/collector.enc` and the admin file), whatever the TOML is called, and they
refuse a `.private` outside the checkout. Inside the live checkout, every command would
therefore still target the live project.

1. Create a new Free project. Never reuse or reset the live one, and note its project ref
   (the first part of its `https://<ref>.supabase.co` URL).
2. Clone the repository into a **different folder**, for example `..\sentra-rehearsal`. Set
   up its own ignored `config/local.toml` and `.private` for the throwaway project, following
   [Stage 3](stage-3-storage.md) (admin file, then `shared-bootstrap`). It installs the same
   reviewed migrations 001–005, so restored rows have identical column types. Nothing is
   copied from the live `.private` except the backup in step 3.
3. Copy only the encrypted backup folder into the rehearsal checkout's `.private/backups/`.
   On the same Windows account, both checkouts read the same local key from the OS vault.
   Elsewhere, recover the key securely, never by chat or email.
4. After `shared-bootstrap`, apply the organization, enrollment and follow-up migrations the
   backup needs, using the same private operator process as for the live project:
   - always `sql/007` and `sql/008` for a full backup;
   - also `sql/009` when `series` appears under `tables`; this restores compact
     readings and their identity sequence as well as the per-field projection;
   - also `sql/010` (Follow-ups, SEN-31) when the live `shared-backup-verify` lists
     `org.follow_ups` and `org.follow_up_events` under `tables`. When they appear under
     `not_installed` instead, the source never had them and 010 is not needed;
   - also `sql/011` (Fitbit sign-in links, SEN-28) whenever it is applied to the live project,
     after 010 if both apply. Hosted sign-ins for linked Fitbit participants are stored in
     `enrollment_private.identities` with a `fitbit-link:` prefix that only 011's check
     constraint accepts. 011 also adds the trigger that protects their operator-managed
     credential. Without it the restore stops on that constraint and rolls back. The
     `fitbit_link_invites` table itself is not backed up; issue new links after recovery.

   The restore checks that backed-up private tables exist on the target before inserting rows.
   Migration 011 changes the identity constraint without changing the backup table list, so check
   its installation separately. The restore also resets the participant-number and identity sequences, which
   needs the admin role used by `shared-restore` to own them; otherwise it stops with a
   permission error and rolls back.

## Steps

```powershell
# live checkout: take the backup and check it offline; note project_url in the result
.venv/Scripts/sentra.exe shared-backup
.venv/Scripts/sentra.exe shared-backup-verify .private/backups/<id>/manifest.enc

# rehearsal checkout (..\sentra-rehearsal), pointing only at the throwaway project
.venv/Scripts/sentra.exe shared-bootstrap --egress-baseline-bytes 0
.venv/Scripts/sentra.exe shared-backup-verify .private/backups/<id>/manifest.enc
.venv/Scripts/sentra.exe shared-restore .private/backups/<id>/manifest.enc --empty-audit --target-project <throwaway-ref>
.venv/Scripts/sentra.exe shared-status
```

**Identity check before writing:** `--empty-audit` refuses to run unless `--target-project`
equals the ref of the project the checkout is configured for. In a rehearsal, that ref must
**differ** from the `project_url` printed by `shared-backup-verify`. If they are equal, stop:
the rehearsal checkout is pointing at the live project. The empty-table check is a second
safety net only.

`shared-restore` checks every member before changing anything. Inside one transaction it
then compares each table's restored row count and order-independent SHA-256 fingerprint
with the manifest, and each original response's digest. It rolls back if any of them
differs. The original responses are uploaded into the rehearsal project's own
`sentra-originals` bucket.

## Record

The owner-created isolated Free project in a separate Free organization was configured
in a separate checkout with new target credentials, SSL enforcement and migrations
001–015. The original live project and its ledger were preserved. The recovery ran
released commit `07678e6af5cdf300374e6e09e77e1f806c1525bc`; no provider requests,
collection restart, derived-board refresh or deletion ran.

Source encrypted-manifest SHA-256:
`33569268be28dcb2ec289d1cee05ced2bd0147de9fe6a3929041c0b3907f402e`.
Comparison is against the coherent source snapshot in that authenticated archive,
not a claim that the live database cannot change after the backup.

| Item | Expected | Actual |
| --- | --- | --- |
| Backup created at / selection | full, after collection paused | Full backup completed November 17 23:00:26 UTC / November 18 Beirut; paused throughout |
| `shared-backup-verify` | `verified`, all installed supported tables and originals | Passed offline before restore: 662 members, 16 tables, 220 originals; `not_covered=[]` |
| Inventory reconciled with the source | Every installed table in the supported allowlist covered; exclusions stated | Seven required audit tables, compact series, four organization/consent tables, two follow-up tables and two enrollment tables; `not_installed=[]`. Intentional exclusions remain below |
| Restore result | `restored_and_verified` | Passed at November 17 23:36:59 UTC / November 18 Beirut |
| Row counts per table | equal to the manifest | All 16 match; 251,971 total rows |
| Table fingerprints | equal to the manifest | All 16 order-independent SHA-256 fingerprints match inside the restore transaction |
| Originals re-hashed | all match | All 220 destination objects downloaded with bounded requests and matched decompressed source digests |
| Compact reconstruction | restored compact arrays expand correctly | 3 compact rows project to 774 readings, equal to the authenticated archive's array lengths |
| Processing from restored data | board and daily features identical to the live run for the same day | Not run; derived outputs were not rebuilt and no new refresh is claimed |
| Time to restore | — | 891.16 seconds including destination-original readback; database/original-upload transaction completed after 782.91 seconds |

The run reserved 897,486,250 bytes within its 1,100,000,000-byte session cap.
A separate bounded progress inspection reserved 98,304 bytes and post-checks
reserved 65,536 bytes; combined recovery reservations were 897,650,090 bytes.
The new organization started with a conservative 20 MB setup/rounding baseline;
its ledger was not substituted for or deducted from the live organization's ledger.
Final measured database size was 307,066,547 bytes and originals occupied 754,343
bytes, below the unchanged database/object guards. Anonymous and unregistered
authenticated roles had no SELECT privilege on any restored table; all restored
identity allocators advanced past their IDs. Provider-credential rows were zero.
Collection and compact writes remained disabled. Private receipts retain source/
target identity, complete count mappings and the dated checks; no values or keys
are published here.

The existing Sentra account could administer the target, and this Windows account
could decrypt the archive with its existing OS-vault key. A second custodian's
independent recovery, off-machine key/backup availability, key-loss recovery and
full derived-output reconstruction remain unverified. No original administrative
access was removed based on this rehearsal.

After an `--empty-audit` restore, membership and consent ids continue after the restored ones,
and enrollment's participant-number allocator moves past the highest restored `pNNN`. A new
participant therefore never collides with a restored one. If the restored IDs already reach the
allocator's maximum (p9999), it is kept at that bound: the restore still succeeds, and new
enrollment reports that capacity is exhausted. These sequence changes are part of the restore
transaction: if the restore stops for any reason, they roll back with the rows and the target's
allocators stay where they were. Record a synthetic test enrollment after the rehearsal if the
enrollment service is deployed against the target.

## Not covered (record as unverified)

- Enrollment browser sessions and rate limits, which are short-lived and excluded on purpose.
- Pending Fitbit sign-in links (`enrollment_private.fitbit_link_invites`). Issue new links
  after recovery if needed.
- Older backups without compact coverage report `audit.series` under `not_covered`.
  Take a fresh backup using #85 before rehearsing a source with 009 installed. Verification
  of an older archive does not establish compact-only recovery. Current backups include
  installed compact rows; the rehearsal must verify their fingerprints, re-expansion and
  processing results before any per-field deletion ([storage plan](storage-plan.md)).
- Provider credentials, storage accounts and keys. They are excluded on purpose, so after
  a real loss participants must reconnect and keys come from secure recovery.
- Parquet tiers and the board. They are derived and rebuilt from the restored audit data.
- Loss of the local encryption key. Without it, backups cannot be read, so the key needs
  its own secure recovery copy.

## Afterwards

After recording the result, obtain explicit authorization to permanently delete the
named throwaway project and its rehearsal copies; they contain participant data.
Keep the verified source archive and recovery evidence. Remove only the rehearsal's
credentials, configuration and copied archive when authorized; preserve unrelated
private files if an existing isolated checkout was reused. Until cleanup is authorized,
keep the project private and collection disabled. A recovery result does not authorize
deletion from the live project.
