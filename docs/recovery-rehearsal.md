# Recovery rehearsal (#30)

Status: **runbook, not yet run.** Run it after a verified backup ([retention-policy.md](retention-policy.md))
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

| Item | Expected | Actual |
| --- | --- | --- |
| Backup created at / selection | full, after collection paused | |
| `shared-backup-verify` | `verified`, N originals, `not_covered` empty. `tables`: the seven supported audit tables plus the installed private tables in the backup allowlist (15 with Follow-ups installed, 13 without) | |
| Inventory reconciled with the source | Compare the migrations applied to the source against `TABLES` and `PRIVATE_TABLES` in [the backup code](../src/sentra/shared_backup.py). Every installed table in that inventory appears under `tables`. Only absent tables from the private allowlist appear under `not_installed` (for example, both follow-up tables before `sql/010`). Record intentional exclusions separately, even when `not_covered` is empty | |
| Restore result | `restored_and_verified` | |
| Row counts per table | equal to the manifest | |
| Table fingerprints | equal to the manifest | |
| Originals re-hashed | all match | |
| Processing from restored data | board and daily features identical to the live run for the same day | |
| Time to restore | — | |

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
- Compact readings (`audit.series`, added by `sql/009`). If 009 is installed on the source,
  record compact-series recovery as unverified in this rehearsal. In particular, verification
  of the backed-up tables does not establish recovery of readings stored only in the compact
  table. See the [storage plan](storage-plan.md) before any deletion of per-field rows.
- Provider credentials, storage accounts and keys. They are excluded on purpose, so after
  a real loss participants must reconnect and keys come from secure recovery.
- Parquet tiers and the board. They are derived and rebuilt from the restored audit data.
- Loss of the local encryption key. Without it, backups cannot be read, so the key needs
  its own secure recovery copy.

## Afterwards

Delete the throwaway project, the rehearsal checkout's `.private` and the restored copies once
the results are recorded. They contain participant data.
