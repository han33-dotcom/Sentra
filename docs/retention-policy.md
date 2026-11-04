# Interim retention and backup policy

Status: **proposal for team agreement (#29)**. Nothing in this document deletes data or
enables an expiry. Every period below is a proposal, and the faculty advisor and the AUB IRB
have the final say on it. Sources are in [retention-evidence.md](retention-evidence.md)
(numbers in brackets refer to its reference list). The storage design it relies on is in
[storage-plan.md](storage-plan.md).

## Principles

1. **Keep what the purpose needs, and no longer.** Health data is a special category, and
   detailed time series can identify people even without names [1, 20, 21]. Detailed
   readings therefore get the shortest life and daily summaries a longer one.
2. **History is never collapsed.** Daily features are kept day by day through the
   evaluation. They are never averaged into one value.
3. **Nothing is deleted without a verified copy and a team decision.** See the gates below.
4. **Withdrawal stops collection immediately.** What happens to collected data is stated in
   the consent form [12, 14, 15].

## Retention schedule (proposed)

| Data class | Where | Readily available | Archive | Then | Reason |
| --- | --- | --- | --- | --- | --- |
| Consent history (append-only, incl. withdrawals) | `org.consents`, signed forms with the PI | whole project | — | keep ≥ 3 years after the project ends | AUB IRB manual §6.8 [12]; US Common Rule floor [10] |
| Daily features and sparse daily/session data (sleep, resting HR, HRV, coverage, rule version) | Postgres `audit.records/measurements`, tier `measurements.parquet`, processed outputs | through FYP evaluation (Demo Day, May 2027) | — | IRB decision at project close: delete, or keep de-identified aggregates | needed for baselines and evaluation; a few KB per person-day |
| Detailed series (minute rollups, original-resolution HR) | Postgres | **short window, proposed 30 days** (matches the 30-day `hr_raw` hot tier and covers the 3-day correction rechecks) | compressed Parquet tiers (~100 KB per person-day) | delete at project close | most identifying data class [20, 21]; dominant storage cost |
| Original API responses (compressed, hash-verified) | private bucket `sentra-originals` | whole project | — | delete at project close | the lossless source that lets everything else be rebuilt |
| Encrypted backups | offline, in a private location held by the custodian, plus a second separate copy | latest 3 verified backups, at most **90 days** each | — | expire | 3-2-1 rule [19]; deletions reach backups within a known window [16] |
| Authorized downloads / exports | the recipient's private location | as needed | — | the recipient deletes them within 30 days | downloads cannot be recalled |
| Provider credentials | `collector_private` | while connected | — | disabled at withdrawal (already transactional) | no longer needed |

The 30-day detail window and the 90-day backup life are set again after the compaction
measurements in #46 and #50. The window is sized to the correction and reprocessing window,
not to the 28-day baseline, because baselines use daily values.

## Withdrawal (proposed)

- **Immediately:** collection stops and the person is hidden from the dashboard, the API and
  group statistics (already implemented, #33 and #52).
- **Within 30 days, after a preview:** an admin deletes the person's detailed series and
  original responses, and removes their daily features from published outputs.
- **Kept:** the consent and withdrawal record, which is required [12]. Group statistics
  already published from 5 or more people are not recomputed. Using GDPR Art. 17(3)(d) to
  keep anything else needs the consent form to say so and IRB approval [15].
- **Backups:** the person's data leaves them as backups expire (at most 90 days). This must
  be stated in the consent form.

## Backups

- Use the existing `shared-backup` command. It is encrypted with the local key, takes one
  consistent read-only snapshot of the audit tables and includes every original response.
  It contains no OAuth credentials, storage accounts or passwords. Keep the key separate from
  the backup copies [16].
- **Verify every backup offline** with `shared-backup-verify` before relying on it. The check
  decrypts every member and compares the row count and fingerprint of each table, and the
  digest of each original response, against the manifest. It needs no database or storage
  access.

  ```powershell
  .venv/Scripts/sentra.exe shared-backup
  .venv/Scripts/sentra.exe shared-backup-verify .private/backups/<id>/manifest.enc
  ```

- **Coverage:** a full backup also includes the consent history and organization tables
  (`org.organizations`, `org.org_users`, `org.memberships`, `org.consents`) and the enrollment
  invitations and provider identities (`enrollment_private.invites`, `identities`). They are read
  by the admin role inside the same database snapshot as the audit tables, so the full backup
  needs `.private/supabase-admin.json`. Excluded on purpose: credentials, enrollment browser
  sessions and rate limits. Partial (`--participant`/`--provider`/`--dataset`) and `--audit-only`
  backups contain the audit tables only, and `shared-backup-verify` lists what they do not cover
  (`not_covered`). Only a full backup with an empty `not_covered` satisfies the gates below.
  These tables force row-level security, so the backup reads them with `row_security = off`.
  An admin connection without bypass rights therefore stops the backup with an error, instead
  of silently backing up no rows.
- Supabase Free's own backups are not relied on; this was not verified.

## Gates before any destructive storage step (#46)

All of the following, recorded in the task:

1. The team has agreed this policy (or a revised version).
2. A fresh backup taken **after** collection was paused, verified offline with
   `shared-backup-verify` (store the JSON result in the task, not the backup).
3. That backup was restored and compared in isolation ([recovery-rehearsal.md](recovery-rehearsal.md), #30).
4. The step's own lossless check passed, and a preview of the rows it would remove was
   reviewed.
5. Both code owners approved, during a paused window.

## Decisions needed

1. Approve or change the detail window (30 days), the backup life (90 days) and the
   withdrawal handling above.
2. Ask the advisor or IRB for the data-retention period at project close, and whether
   Lebanese Law 81/2018's health-data licence or its exemption for educational institutions
   applies [7–9].
3. Name the custodian (the faculty PI or advisor) for backups and records after the project [12].
