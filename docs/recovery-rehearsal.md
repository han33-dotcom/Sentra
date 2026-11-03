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

Use a **separate, throwaway Supabase Free project** owned by the operator:

1. Create a new Free project. Never reuse or reset the live one.
2. Point a separate, ignored local configuration at it, and run
   `sentra shared-bootstrap --egress-baseline-bytes 0` there. This installs the same reviewed
   migrations 001–005, so the restored rows have identical column types.
3. Copy the encrypted backup beneath that configuration's `.private/backups/`, together with
   the same local encryption key (from the OS vault, never by chat or email).

## Steps

```powershell
# live configuration: take the backup and check it offline
.venv/Scripts/sentra.exe shared-backup
.venv/Scripts/sentra.exe shared-backup-verify .private/backups/<id>/manifest.enc

# rehearsal configuration (throwaway project): restore into its empty audit tables
.venv/Scripts/sentra.exe --config config/rehearsal.toml shared-restore .private/backups/<id>/manifest.enc --empty-audit
.venv/Scripts/sentra.exe --config config/rehearsal.toml shared-status
```

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

Delete the throwaway project and the restored copies once the results are recorded. They
contain participant data.
