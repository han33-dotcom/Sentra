# Sentra: wearable data pipeline and wellness layer

Coding agents: start with [AGENTS.md](AGENTS.md) and
[agent-owned delivery](docs/local-delivery.md). The implementation agent takes each
task through self-review, acceptance, CI, develop and main. See
[collaborator setup](docs/collaborator-setup.md#shared-policy-discovery-and-refresh)
for automatic instruction loading and the one-time refresh after policy updates.

Sentra is the wearable-data pipeline for our final-year project. It collects data
for consenting participants through Google Health v4 (Fitbit) and WHOOP v2. Each response is stored privately and
unchanged, then normalized conservatively into Supabase PostgreSQL. A private
research viewer sits on top.

On top of that collection, the repository also includes:
- compact parquet storage tiers;
- a v0 wellness processing layer;
- a read-only API and Docker deployment;
- the project website.

**Stages 1–7 and the viewer redesign are complete within the agreed MVP scope.**
Automatic collection is **paused**. Merging or deploying code never restarts it.

Start with the [operating guide](docs/operating-guide.md) and the
[data dictionary](docs/data-dictionary.md). The
[private Sentra viewer](https://sentra-wearable-audit.streamlit.app) is available to
approved team accounts.

## Architecture

```
Google Health v4 / WHOOP v2
  -> GitHub Actions collector (collect.yml, paused)  -> Supabase Storage sentra-originals (unchanged responses)
                                                     -> Supabase Postgres audit.* (records, measurements, runs)
Participant phone -> enrollment service (Render)     -> Supabase Postgres org.* (memberships, consent history)
Wellness refresh (reads audit, publishes results)          -> sentra-tiers: parquet tiers, processing, board.json
Streamlit private viewer (read-only role)            -> team pages; organization overview, profiles,
                                                        trends and follow-ups within each user's permissions
Read-only FastAPI (operator or scoped org user)              -> pseudonymous processed outputs
```

Components, hosting, database roles, migrations and privacy boundaries:
[architecture](docs/architecture.md). Operating procedures by situation:
[operator handover](docs/handover.md).

## What the pipeline does

1. **Extract:** authenticate with each provider and request bounded date ranges,
   following every returned page. Provider failures are handled independently. Every
   hosted job records one outcome: `records`, `no_records`, `denied` (HTTP 401 after
   a refresh, or 403) or `failed`.
2. **Preserve:** save unchanged API response bodies as compressed private objects,
   with integrity hashes, request metadata and source references in PostgreSQL.
3. **Validate and normalize:** check record structure and stable identities, then
   organize returned fields into records, measurements and sessions. Known units and
   classifications are attached; original values and timing information are kept.
4. **Load:** write the structured records into Supabase PostgreSQL. Unchanged
   rechecks avoid duplicate records. Corrections replace the current structured
   record, while the original responses are kept.
5. **Inspect and export:** use the private viewer or the CLI to examine returned
   data, availability, provenance and collection status, then create private extracts.
6. **Tier, process and serve (operator steps):**
   - Build parquet tiers from the audit tables.
   - Derive v0 wellness features from the tiers.
   - Serve the features through the read-only API.

Normalization is conservative:
- Missing values stay missing and unknown fields remain available.
- Selected identifying fields are removed from normalized records. Original
  responses stay private and can contain identifying fields.
- The pipeline does not fill gaps, remove statistical outliers, smooth signals or
  make health predictions.
- An API response may already contain a provider summary or score; it is not
  necessarily a raw sensor signal.

## Data collected

| Provider | Collection scope |
| --- | --- |
| Fitbit / Google Health | Daily steps, distance, total calories, active-zone minutes, active minutes and heart rate |
| Fitbit / Google Health | Daily resting heart rate, HRV, oxygen saturation, respiratory rate, sleep temperature derivations and VO2 max, where returned |
| Fitbit / Google Health | Sleep and exercise session records |
| Fitbit / Google Health | Sedentary periods and sleep respiratory-rate summaries (probe: October 3–9, 2026) |
| Fitbit / Google Health | Requested 60-second rollups for steps, distance, total calories, active-zone minutes and heart rate |
| Fitbit / Google Health | One representative original-resolution heart-rate day from the initial import |
| Fitbit / Google Health | Activity-level intervals: **on request only**; October 9, 2026 collected, October 3–8 deferred for storage ([details](docs/data-dictionary.md#extra-fitbit-datasets-october-2026)) |
| WHOOP | Cycles, recovery, sleep and workouts, including returned summaries, score states and vendor scores |

**Initial import** (September 8–October 7, 2026):
- Minute rollups were limited to October 1–7.
- Original heart rate was limited to one representative day.
- Later bounded recovery extended the applicable datasets through October 9.

**Notes:**
- WHOOP's integration provides session and cycle summaries, not continuous
  heart-rate samples.
- Requesting minute resolution does not guarantee a reading for every minute.
- The three newer Fitbit datasets are covered by the existing authorization
  (`activity_and_fitness`, `health_metrics_and_measurements`), so no reconnect is
  needed.
- Activity level costs about 22.9 MB of database per participant-day. It is
  excluded from the daily, initial and recovery plans, and runs only when a manual
  run names it.

See the [collection contracts and evidence](docs/stage-2-collection.md).

## Delivery

| Stage | Delivered | Evidence and instructions |
| --- | --- | --- |
| 1 — Foundation and authorization | Python CLI, provider configuration checks, participant authorization, encrypted local token/sample storage and demonstrated token renewal | [Stage 1](docs/stage-1-setup.md) |
| 2 — Extraction and normalization | Bounded imports, pagination and resume, stable record identities, correction rechecks, source verification, private JSON/CSV/original exports and a reviewed schema | [Stage 2](docs/stage-2-collection.md), [schema](docs/schema.md) |
| 3 — Shared storage | Private Supabase PostgreSQL and original-object storage, separate collector/viewer roles, capacity and egress guards, encrypted backups and selected restore verification | [Stage 3](docs/stage-3-storage.md) |
| 4 — Cloud collection | Hosted encrypted credential ownership, safe refresh/handoff/reconnect, GitHub Actions execution, missed-date recovery, a midnight Beirut schedule and explicit pause controls | [Stage 4](docs/stage-4-collection.md) |
| 5 — Private viewer | Deployed Streamlit application, Google identity sign-in, approved-account access, bounded filters, audit evidence and verified downloads | [Stage 5](docs/stage-5-viewer.md) |
| 6 — Verification and operations | Synthetic and selected live checks for pagination, corrections, renewal, provider isolation, timezone boundaries, permissions, exports, capacity and backup restoration; two participant-app comparisons confirmed by the user | [Stage 6](docs/stage-6-validation.md), [operating guide](docs/operating-guide.md) |
| 7 — Research dataset | Approved October 7–9 backfill for both participants, verified retained week coverage and collection left paused for use-case research | [Stage 7](docs/stage-7-audit-plan.md) |
| Viewer redesign | Pale sidebar, white panels and charcoal summaries; readable metric definitions, charts and tables, mobile layout, keyboard navigation and retained detailed audit access | [Redesign validation](docs/viewer-redesign-validation.md) |
| Extra Fitbit datasets | `sedentary-period` and `respiratory-rate-sleep-summary` in the job plan, `activity-level` on request; per-job outcomes; viewer labels and per-day period totals; October 3–9 probe | [Data dictionary](docs/data-dictionary.md#extra-fitbit-datasets-october-2026) |
| Parquet tiers | `sentra tiers-build`: hot raw heart rate (30 days), warm minute heart rate, measurements and sessions as zstd parquet in a private bucket, with a size report | [Parquet tiers](docs/parquet-tiers.md) |
| Processing layer | Canonical metric mapping, minute grid, daily features, 28-day personal baselines, v0 wellness flags and a k-anonymous cohort | [Processing](docs/processing.md) |
| Read API and Docker | Read-only FastAPI over processed outputs; Compose runs only the API and the processing job | [Read API](docs/read-api.md) |
| Repository rules | CI (`guard`, `test`), data guard, pre-commit hooks, PR template, code owners and branch model | [Contributing](CONTRIBUTING.md) |
| Website | Static project site published to GitHub Pages | [website/README.md](website/README.md) |
| Wellness board | Private board refreshed from stored readings (latest day, wellness timeline, trends) inside the private viewer | [Wellness board](docs/wellness-board.md) |

**Viewer.** The viewer’s four data exploration pages are **Daily activity**, **Sleep**,
**Workouts** and **Data availability**.
- Sleep uses its Beirut wake date and workouts use their start date.
- WHOOP recovery links to sleep through the provider's sleep ID.
- Display conversions give readable units without changing stored source values.
- Ambiguous sources stay distinguishable. Missing days are not interpolated or
  replaced with zeros.
- Readable CSV, detailed audit CSV and original-response downloads keep the
  appropriate values, units, timing and provenance.
- Participant or filter changes and sign-out clear prepared results and downloads.

**Wellness layer.** The processing outputs are **wellness indicators relative to
each person's own recent pattern**.
- They are not medical assessments and must never be presented as a diagnosis.
- All thresholds in `src/sentra/processing/thresholds.json` are
  **v0 — pending medical expert sign-off**.
- Cohort days with fewer than 5 people are suppressed. Each statistic needs five eligible contributors for that device and date.

The stage documents also contain historical evidence and earlier decisions. The
current collection decision is the bounded, paused state described here and in the
operating guide.

## Current operational state

Five Fitbit and five WHOOP participants contributed readings for November 23–24. The private dashboard was refreshed and verified on November 26. Regular collection is paused. The owner retained Supabase Pro, a 4.5 GB monthly transfer stop and no additional spend. [November sprint closeout](docs/sprint-closeout.md) · [Historical capacity measurements](docs/capacity-measurements.md)

## Local development

Use Python **3.11**. From the repository root in Windows PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-windows.txt
.venv/Scripts/python.exe -m pip install --no-deps -e ".[dev,viewer]"
.venv/Scripts/python.exe -m pip install "streamlit[auth]==1.65.0" "Authlib==1.8.0" "reportlab==5.0.1" -r requirements-api.txt httpx pytest pre-commit
.venv/Scripts/python.exe -m pip check
.venv/Scripts/pre-commit.exe install
.venv/Scripts/python.exe -m pytest
.venv/Scripts/sentra.exe --help
```

**Requirements files:**
- Hosted collection uses `requirements-cloud.txt`.
- The Streamlit application uses `viewer/requirements.txt` and `viewer/app.py`.
- The processing job and API image use `requirements-cloud.txt` +
  `requirements-api.txt`.

**Operators:** a new operator follows the stage instructions to create ignored local
configuration, initialize the OS-backed encryption key and authorize the agreed
participants. An existing operator must preserve their configuration and keys.
Cloning this repository gives no access to participant data or tokens.

With an already configured operator checkout, these commands make no wearable
requests:

```powershell
.venv/Scripts/sentra.exe shared-status
.venv/Scripts/sentra.exe shared-growth                       # storage per dataset
.venv/Scripts/sentra.exe cloud-window --pause
.venv/Scripts/sentra.exe tiers-migrate                       # once: private sentra-tiers bucket
.venv/Scripts/sentra.exe tiers-build --local .private/tiers  # dry run + size report
.venv/Scripts/sentra.exe tiers-build                         # publish tiers
.venv/Scripts/sentra.exe process-run --from-bucket           # v0 wellness features into .private/processed
```

**Manual recovery** requires an explicitly approved provider and date scope. CLI end
dates are **exclusive**, while the viewer's displayed end date is **included**. Do
not repeat an entire initial import to fix one missing dataset. See the operating
guide for bounded recovery, reconnects, backups and failure handling, and the
[data dictionary](docs/data-dictionary.md#bounded-probe-results-october-39-2026)
for the new-dataset probe.

**Read API.** To run the read API and the processing job in Docker:

```powershell
Copy-Item .env.example .env    # SENTRA_API_KEY and viewer-only SENTRA_PROCESSING_CONFIG; .env is git-ignored
docker compose up -d --build   # API on http://127.0.0.1:8000
```

## Contributing

Work on focused branches and open a PR into `develop`. The implementation agent records its self-review and acceptance checks. Required CI gates the squash merge. Release `develop` to `main` and synchronize its history back through PRs. The data guard (`scripts/check_no_data.py`, also a
pre-commit hook) and gitleaks block health data, exports and secrets. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Verification, privacy and remaining work

**Tests.** CI runs the Python suite and the JavaScript regressions on Ubuntu and
Windows with Python 3.11 for every PR; opt-in live and PostgreSQL tests stay skipped
there. Each PR records its own results, and the [evaluation table](docs/evaluation.md)
records the sprint evidence.

**Live checks.** Selected live checks were run separately during the stages,
including permission denials, source integrity, token renewal, a private restore
rehearsal and hosted viewer downloads. Desktop, mobile and keyboard checks covered
the redesign. The detailed evidence states which checks were synthetic, live,
user-reported or still unverified. The tier, processing and API layers are verified
with synthetic data and a container smoke test. Their first operator run on the
shared project (October 11) also succeeded.

**Privacy.**
- Keep health records, original responses, exports, backups, parquet tiers,
  processed outputs, tokens, client secrets, encryption keys and consent documents
  out of Git.
- Ignored configuration and private files, and separate least-privilege credentials,
  are required.
- The viewer, the tier reader and the processing job use the read-only
  `sentra_viewer` role. The viewer uses an identity-only Google client and receives
  no provider-token bundle or admin credentials.
- The team-only API reads processed files. Optional organization access uses a restricted database reader to check current roles and consent on each request. Provider credentials stay outside the API.

**Limits.**
- This MVP is a usable basis for project research. It does not establish device
  accuracy, cross-provider equivalence, clinical validity or a production service
  guarantee.
- Google authorization in Testing mode has a short refresh-token lifetime, so
  reconnects remain an operational dependency.
- The approved compaction verified one bounded removal. New collection and further removals require separate estimates and approval.
- Full replacement-project disaster recovery and off-machine key recovery remain
  unverified.
- Processing uses Fitbit sleep stages where supplied and WHOOP nightly totals. MET-based activity fields remain empty. Wellness thresholds require medical expert sign-off.

## Team workspace

Use the [documentation index](docs/README.md) and [team workflow](docs/team-workflow.md).
Software tasks live in GitHub Issues and the project board; technical documents stay
in this repository. Meeting notes and general references belong in the Wiki after
publication. [Team workflow](docs/team-workflow.md) records the rollout status. [Local delivery](docs/local-delivery.md) describes agent-owned review, acceptance and release.
