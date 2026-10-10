# Sentra — Sprint 5: wearable ETL MVP

Sentra is a working wearable-data pipeline for our final-year project. Sprint 5
established extraction, validation and normalization, private storage, resumable
cloud collection, a private research viewer and operational verification for two
consenting participants: one Fitbit Air account through Google Health v4 and one
WHOOP account through WHOOP v2.

**Stages 1–7 and the viewer redesign are complete within the agreed MVP scope.**
Stage 7 concluded with a bounded research dataset, replacing the earlier proposal
for continuous observation. Automatic collection is paused. The next step is to
inspect the retained data and choose project use cases; continuous collection,
storage scaling and production hardening remain future work.

The [private Sentra viewer](https://sentra-wearable-audit.streamlit.app) is available
to approved team accounts. Start with the [operating guide](docs/operating-guide.md)
and [data dictionary](docs/data-dictionary.md).

## What the pipeline does

1. **Extract:** authenticate with each provider and request bounded date ranges,
   following all returned pages. Provider failures are handled independently.
2. **Preserve:** save unchanged API response bodies as compressed private objects,
   with integrity hashes, request metadata and source references in PostgreSQL.
3. **Validate and normalize:** check record structure and stable identities,
   organize returned fields into records, measurements and sessions, attach known
   units and classifications, and retain original values and timing information.
4. **Load:** write the structured records into Supabase PostgreSQL. Unchanged
   rechecks avoid duplicate records; corrections replace the current structured
   record while original responses remain retained.
5. **Inspect and export:** use the private viewer or CLI to examine returned data,
   availability, provenance and collection status, then create private extracts.

This is conservative normalization. Missing values stay missing, unknown fields
remain available, and selected identifying fields are removed from normalized
records. Original responses remain private and can contain identifying fields.
The pipeline does not fill gaps, remove statistical outliers, smooth signals or
create health predictions. An original API response may already contain a
provider summary or score; it is not necessarily a raw physical sensor signal.

## Data collected

| Provider | Collection scope |
| --- | --- |
| Fitbit / Google Health | Daily steps, distance, total calories, active-zone minutes, active minutes and heart rate |
| Fitbit / Google Health | Daily resting heart rate, HRV, oxygen saturation, respiratory rate, sleep temperature derivations and VO2 max, where returned |
| Fitbit / Google Health | Sleep and exercise session records |
| Fitbit / Google Health | Requested 60-second rollups for steps, distance, total calories, active-zone minutes and heart rate |
| Fitbit / Google Health | One representative original-resolution heart-rate day from the initial import |
| WHOOP | Cycles, recovery, sleep and workouts, including returned summaries, score states and vendor scores |

The initial import requested September 8–October 7, 2026, with minute rollups
limited to October 1–7 and original heart rate limited to one representative day.
Later bounded recovery extended the applicable datasets through October 9.
WHOOP's integration provides session/cycle summaries rather than continuous
heart-rate samples. Requested minute resolution does not guarantee a reading
for every minute. See the [collection contracts and evidence](docs/stage-2-collection.md).

## Sprint 5 delivery

| Stage | Delivered | Evidence and instructions |
| --- | --- | --- |
| 1 — Foundation and authorization | Python CLI, provider configuration checks, participant authorization, encrypted local token/sample storage and demonstrated token renewal | [Stage 1](docs/stage-1-setup.md) |
| 2 — Extraction and normalization | Bounded imports, pagination and resume, stable record identities, correction rechecks, source verification, private JSON/CSV/original exports and a reviewed schema | [Stage 2](docs/stage-2-collection.md), [schema](docs/schema.md) |
| 3 — Shared storage | Private Supabase PostgreSQL and original-object storage, separate collector/viewer roles, capacity and egress guards, encrypted backups and selected restore verification | [Stage 3](docs/stage-3-storage.md) |
| 4 — Cloud collection | Hosted encrypted credential ownership, safe refresh/handoff/reconnect, GitHub Actions execution, missed-date recovery, a midnight Beirut schedule and explicit pause controls | [Stage 4](docs/stage-4-collection.md) |
| 5 — Private viewer | Deployed Streamlit application, Google identity sign-in, approved-account access, bounded filters, audit evidence and verified downloads | [Stage 5](docs/stage-5-viewer.md) |
| 6 — Verification and operations | Synthetic and selected live checks for pagination, corrections, renewal, provider isolation, timezone boundaries, permissions, exports, capacity and backup restoration; two participant-app comparisons confirmed by the user | [Stage 6](docs/stage-6-validation.md), [operating guide](docs/operating-guide.md) |
| 7 — Research dataset | Approved October 7–9 backfill for both participants, verified retained week coverage and collection left paused for use-case research | [Stage 7](docs/stage-7-audit-plan.md) |
| Viewer redesign | Pinterest-inspired pale sidebar, white panels and charcoal summaries; readable metric definitions, charts and tables, mobile layout, keyboard navigation and retained detailed audit access | [Redesign validation](docs/viewer-redesign-validation.md) |

The redesigned viewer has **Daily activity**, **Sleep**, **Workouts** and
**Data availability** views. Sleep uses its Beirut wake date, workouts use their
start date, and WHOOP recovery links to sleep through the provider's sleep ID.
Display conversions provide readable units without changing stored source
values. Ambiguous sources stay distinguishable, and missing days are not
interpolated or replaced with zeros. Readable CSV, detailed audit CSV and original
response downloads retain the appropriate values, units, timing and provenance.
Participant/filter changes and sign-out clear prepared results and downloads.

Stage documents also contain historical evidence and earlier decisions. The
current collection decision is the bounded, paused state described here and in
the operating guide.

## Current operational state

Snapshot verified on **October 10, 2026 at 15:58 Beirut time**:

- October **7–9** backfill succeeded for both providers: **57 Google jobs and 12
  WHOOP jobs**, with no collection failures. The final date is October 9 because
  October 10 was still incomplete.
- Retained requested coverage includes **October 3–9** across the recurring
  datasets. Google minute request coverage spans **October 1–9**. Original heart
  rate remains the single initial representative day.
- Some requests returned no records, including Google sleep on October 9.
  Completed request coverage does not prove uninterrupted measurements or
  availability of every metric.
- Both automatic execution controls are disabled: the GitHub scheduling variable
  and the database daily-collection control. Merging or deploying code does not
  authorize restarting collection.
- Database ceiling: **400 MB**, with a **20 MB reserve**, giving an effective
  **380 MB import limit** before estimated next-batch checks.
- Database use: **287.56 MB**; approximately **92.44 MB** remains before the import
  limit. Private original objects use approximately **0.73 MB**. These are decimal
  MB and a dated snapshot, not a live quota reading.
- Object and monthly egress ceilings remain **700 MB** and **3.5 GB** respectively.
  Egress tracking uses a verified baseline plus conservative reservations rather
  than a billing meter. Its baseline must be checked at least weekly and at each
  new UTC month.

The collector settings already use the new database ceiling. The hosted viewer's
capacity indicator requires its managed settings to be updated separately if it
still shows the older ceiling. A midnight workflow is configured, but successful
unattended midnight collection has not been demonstrated during this paused
research phase.

## Local development

Use Python **3.11**. From the repository root in Windows PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-windows.txt
.venv/Scripts/python.exe -m pip install --no-deps -e .
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -m unittest discover -s tests
.venv/Scripts/sentra.exe --help
```

For a new operator, follow the stage instructions to create ignored local
configuration, initialize the OS-backed encryption key and authorize agreed
participants. An existing operator must preserve their configuration and keys.
Cloning this repository does not provide access to participant data or tokens.
Hosted collection uses `requirements-cloud.txt`; the Streamlit application uses
`viewer/requirements.txt` and `viewer/app.py`.

With an already configured operator checkout, these checks make no wearable
requests:

```powershell
.venv/Scripts/sentra.exe shared-status
.venv/Scripts/sentra.exe cloud-window --pause
```

Manual recovery requires an explicitly approved provider/date scope. CLI end
dates are **exclusive**, while the viewer's displayed end date is **included**.
Do not repeat an entire initial import to resolve one missing dataset. See the
operating guide for bounded recovery, reconnects, backups and failure handling.

## Verification, privacy and remaining work

The current automated suite contains **117 tests**; the most recent complete run
passed with **five opt-in live integration tests skipped**. Selected live checks
were run separately during the stages, including permission denials, source
integrity, token renewal, private restore rehearsal and hosted viewer downloads.
Desktop/mobile and keyboard checks covered the redesign. Detailed evidence states
which checks were synthetic, live, user-reported or still unverified.

Keep health records, original responses, exports, backups, tokens, client secrets,
encryption keys and consent documents outside Git. Ignored configuration/private
files and separate least-privilege credentials are required. The viewer uses an
identity-only Google client and receives no provider-token bundle or admin
credentials. Access is restricted to approved accounts and the agreed team.

This MVP provides a usable basis for project research. It does not establish
device accuracy, cross-provider equivalence, clinical validity or a production
service guarantee. Google authorization in Testing mode has a short refresh-token
lifetime and remains an operational reconnect dependency. Storage growth prevents
indefinite collection at the current representation. Lossless context compaction
was investigated, but no storage migration has been applied. Full replacement-
project disaster recovery and off-machine key recovery remain unverified.

Choose the research question using observed coverage, definitions, gaps and
delivery behavior. Add use-case-specific quality rules only after that decision,
and revisit storage scaling and continuous collection when they are needed.
