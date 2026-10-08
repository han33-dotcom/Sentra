# Stage 3 implementation plan

> Implement inline with the executing-plans skill; preserve ETL-pipeline and existing changes.

**Goal:** Put the existing two-participant audit workspace in private Supabase Free storage, with bounded writes and a demonstrated backup restoration.

**Architecture:** PostgreSQL stores searchable measurements, complete normalized record context, original-response manifests and durable import state. Compressed unchanged responses live in one private Storage bucket. Separate PostgreSQL login roles and restricted Supabase Auth service accounts give the collector writes and the future viewer reads; neither viewer credential can access provider tokens. OAuth migration and scheduled collection remain Stage 4 work.

**Constraints:** Free organization only; no billing upgrades or paid add-ons. No health data or credentials in Git/logs. Thresholds below 500 MB database, 1 GB objects and 5 GB uncached egress. Preserve provider times including civil/unknown time. No invented completeness. No scheduler or viewer app.

**Review focus:** interrupted object/database writes, changing records with removed metrics, account-wide quota uncertainty, failed source hashes, viewer privilege escape, corrupted backups and restoring over existing data.

## Tasks

- [x] Test then implement conservative quota configuration and encrypted hosted credentials.
- [x] Deployable SQL with least-privilege roles, RLS, private Storage policies and a read-only storage-usage function.
- [x] Test then implement resumable local-to-cloud synchronization, source verification and correction upserts. Progress follows durable data.
- [x] Test then implement health-only backup and non-destructive isolated restoration/verification; document separate credential recovery.
- [x] Add CLI/setup instructions, establish Free project, upload existing imports and demonstrate access denial and a small restoration.
- [x] Finish the final full source/content comparison; record outcome and stop before Stage 4.

## Execution ledger

- Branch verified: ETL-pipeline. User explicitly authorized implementation within Stage 3; no extra design approval, branch or commit required.
- Official pricing checked 8 October 2026: Free 500 MB DB, 1 GB Storage, 5 GB uncached and 5 GB cached egress, two active projects, inactivity pause after one week, no automatic backups. Pro spending cap is not a Free control.
- Free organization/project created with user sign-in and user-entered database password. Sentra project `jpweubkzwbjvydwblfmm`, Frankfurt/Nano, private originals bucket, server SSL enforcement and certificate-verified session-pooler connections. No payment/add-on/upgrade.
- Both imports uploaded: Google 61,656 records / 138,141 scalar measurements / 37 sessions / 286 manifests; WHOOP 137 / 2,586 / 107 / 8. Provider tokens remain local.
- Actual conservative guard stopped a Google sleep batch; lossless common-context compaction allowed the outstanding 26 records to resume. No discarded fields, deletion or duplicate import.
- Full rerun: zero changed records and zero uploaded manifests for both providers; 61,656 Google and 137 WHOOP records unchanged.
- Viewer reads all 61,793 records and a private original; health/Storage writes, private credentials and collector-role escalation denied. Anonymous original access denied with a provider permission response, not a timeout/service-error assumption.
- Real selected WHOOP sleep backup: 71,872 encrypted bytes; fresh-process restoration to private `sentra_restore_66afba6cc893` passed counts, row fingerprints and original hashes. Restored 30 records/sessions, 780 measurements, two manifests, one participant/state and six run records. Main audit tables preserved. No full-workspace or new-project disaster recovery claimed.
- Root-cause fixes: materialized JSON context removes wide-record verification timeout (600-metric synthetic test failed at two seconds before fix and passed after); exact Decimal numeric adaptation and versioned migration003 remove float8-to-numeric rounding (high-precision synthetic test failed before fix and passed after). Preserved record JSON/originals and hashes did not change.
- Final synthetic suite: 56 passed, two opt-in cloud tests skipped. Separately enabled both cloud tests: passed with synthetic participant writes rolled back, including correction/removal, value/session corruption detection, atomic rollback, wide/precise values, refusal to restore over populated data and corrupt restore rollback.
- Dependency check passed, Python compilation passed, all three SQL migrations parsed, Git whitespace check passed. Private/admin/runtime files and local config confirmed ignored. Branch remains ETL-pipeline; no scheduler, branch creation, commit or push.
- Independent follow-up review: no remaining important defects found after fixes; reviewer used code/synthetic fixtures only.
- Final fresh-process `shared-verify all --originals`: passed for all Google/WHOOP counts, local and remote JSON hashes, searchable measurement/session contents and all 156 Google plus eight WHOOP unique original objects. Earlier timeout/precision failures were resolved before this successful check.
- Measured final database 268,662,451 bytes, audit tables/indexes 255,311,872; private originals 655,605 bytes; local private workspace 79,960,291 bytes. Egress status is conservative reservations, not actual billing. Small restore/test allocations retained.
- Capacity finding: approximately 61 MB below effective guard; minute datasets initially average about 17.3 MB/requested day. On 8 October 2026 the user approved a three-day initial observation instead of two weeks, retaining existing imports and labeling findings preliminary. Three days add roughly 52 MB for minute datasets alone, so capacity still needs verification before scheduling/start approval; safe stops remain. See [updated audit plan](stage-7-audit-plan.md). Baseline must be checked weekly/new month; Free pause and operator off-machine recovery-copy responsibilities documented.
