# Recovery rehearsal (#30)

Status: **runbook, not yet run.** Run it after a verified backup ([retention-policy.md](retention-policy.md))
and before any destructive storage step (#46). Record the results table below in the task,
never the backup itself. NIST SP 800-34 treats restoring from backup media as part of
contingency testing (see [retention-evidence.md](retention-evidence.md), reference 16).

## Where to restore

**Not into the live project.** `shared-restore` without `--empty-audit` creates an isolated
`sentra_restore_*` schema in the *same* database. Before writing, its capacity guard requires
current usage plus about 8 × the backup's uncompressed table size to fit under the 400 MB
database guard. At the last measurement the live database used 310 MB (storage-plan.md), so
a full rehearsal there would be refused, and it would compete with collection headroom anyway.

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
| `shared-backup-verify` | `verified`, 7 tables, N originals | |
| Restore result | `restored_and_verified` | |
| Row counts per table | equal to the manifest | |
| Table fingerprints | equal to the manifest | |
| Originals re-hashed | all match | |
| Processing from restored data | board and daily features identical to the live run for the same day | |
| Time to restore | — | |

## Not covered (record as unverified)

- `org` consent and `enrollment_private` tables, which backups do not include yet (see
  retention-policy.md).
- Provider credentials, storage accounts and keys. They are excluded on purpose, so after
  a real loss participants must reconnect and keys come from secure recovery.
- Parquet tiers and the board. They are derived and rebuilt from the restored audit data.
- Loss of the local encryption key. Without it, backups cannot be read, so the key needs
  its own secure recovery copy.

## Afterwards

Delete the throwaway project, the rehearsal checkout's `.private` and the restored copies once
the results are recorded. They contain participant data.
