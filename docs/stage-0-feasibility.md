# Stage 0: wearable extraction and audit feasibility

Reviewed on **7 October 2026**, using official documentation and direct Cloud Console inspection. Google Health API enablement is confirmed in `sentra-510913`; participant authorization and data access await verification. Subsequent stages await explicit approval. No real-data demonstration by this agent yet.

Stage 0 is complete. The user approved Stage 1 on 7 October 2026; its current
implementation and outstanding account checks are tracked in [Stage 1 setup](stage-1-setup.md).
The findings below record the Stage 0 review rather than live Stage 1 status.

## Decision for review

**Verify and reuse the team's existing Google Health API project**, alongside WHOOP, subject to consent and account setup. The team now reports successful access around a week ago; the exact successful action and current access remain unverified. Use manual Fitbit export ingestion only if API access cannot be confirmed. Retain the proposed stack, adding an application-level approved-user check to Streamlit. No services were provisioned, settings changed, money spent or health data retrieved by this agent.

**Automated daily Fitbit access is pending verification, not established as blocked.** The team's newer report of a working project supersedes the earlier answer that no enabled/approved project existed. Google's notice restricts new-project onboarding; it does not establish that the existing project's access was revoked. Legacy Fitbit API support ended on 30 September 2026 and the API shuts down on 30 October 2026. Verify that the successful request used `health.googleapis.com`, rather than the legacy `api.fitbit.com`, and distinguish a data response from API enablement or OAuth login alone. Do not create a replacement project or build a temporary legacy collector. [Google Health announcement](https://developers.google.com/health)

The user instructed the team to try the new Google Health API rather than treating the onboarding notice as an access gate, then provided the newly created project **`sentra-510913`**, displayed as **Sentra**. Initial inspection found the API absent from its enabled services and a working Library enablement page. After the user enabled it, direct Console inspection confirmed **Google Health API**, service **`health.googleapis.com`**, status **Enabled**, with a **Disable API** control. New-project enablement therefore succeeded for this project despite the published onboarding notice. Do not treat that notice as proof this integration is blocked. Participant OAuth authorization, actual dataset access and background renewal remain unverified. The metrics page shows no traffic data for the selected time frame; this does not demonstrate an authenticated request. The project used for the earlier successful test has not been independently identified. No API was enabled, credentials created or health data retrieved by this agent.

The project's Credentials inventory shows **No OAuth clients to display**, no API keys and no service accounts, with a reminder to configure the consent screen. **Next account step:** configure OAuth consent, read-only scopes, a Web application client and an exact callback URI in the next authorized implementation stage, then verify a small authenticated request and background token renewal. API enablement alone grants no access to the participant's records. Do not activate the optional Cloud trial or add billing for this setup. [Google setup](https://developers.google.com/health/setup)

Manual imports can share the audit schema/viewer but do **not** satisfy automated daily Fitbit updates. Two-provider automation is potentially feasible with the existing project; current data access and background token renewal still need demonstration after authorization.

Scope remains institutional health and safety, with no selected industry, AI model, diagnosis, health-risk scoring or institutional product dashboard. Two participants can inspect API behavior, not validate predictions or general device accuracy.

## Repository findings

| Check | Finding |
| --- | --- |
| Selected branch | `ETL-pipeline`, verified before edits; retained without creating or renaming a branch |
| Starting commit | `3e81f6898b03e0b331f0234db5720fa7fe87467c` |
| Initial working tree | Clean; no unrelated changes |
| Remote | `https://github.com/han33-dotcom/Sentra.git` |
| GitHub metadata | Private repository; default branch `main`; connected account has admin permission |
| Files and implementation | Only `README.md` tracked at the starting commit; no collectors, application, schemas, tests or extraction infrastructure |
| Dependencies/configuration | No dependency manifests, lockfiles, environment examples, `.gitignore`, deployment config or Actions workflows |
| Instructions | No `AGENTS.md` found in the repository or its ancestor directories; README working rules read |
| Local tooling | Python executable available; no project environment or package versions established |

The README's two-Fitbit milestone is superseded. Its Notion links and rules are retained: no credentials, real wearable data or consent documents in Git; synthetic examples only. Supervisor confirmation of ethics and approved storage is required before using participant data as research findings.

## Provider feasibility and data boundaries

### WHOOP: documented path available, real authorization pending

The friend should own developer setup using the existing membership/login; no new subscription is needed. Membership is required for developer access. [WHOOP overview](https://developer.whoop.com/docs/developing/overview/)

Sandbox permits **10 connected WHOOP members** without an approval request, sufficient for this pilot; it uses member data. [WHOOP app tiers](https://developer.whoop.com/docs/developing/app-approval/)

Use the current v2 API at `https://api.prod.whoop.com/developer`. Initial datasets:

| Dataset / GET path | Examples exposed | Interpretation |
| --- | --- | --- |
| Cycles: `/v2/cycle` | Start/end, strain, energy in kJ, average/max heart rate, step count | Vendor cycle summaries and scores |
| Recovery: `/v2/recovery` | Recovery score, resting HR, HRV RMSSD in ms, SpO2 %, skin temperature in Celsius, calibration state | Vendor score and calculated physiological summaries |
| Sleep: `/v2/activity/sleep` | Session times, nap flag, stage/no-data durations in ms, respiratory rate, sleep need and performance/consistency/efficiency percentages | Vendor inferred stages, summaries and scores |
| Workouts: `/v2/activity/workout` | Session/activity IDs, times, strain, average/max HR, energy in kJ, distance/altitude in m, zone durations in ms, recorded percentage | Vendor workout summaries and scores |

Collections have time filters and pagination (default 10, maximum 25 records/page); send `next_token` back as `nextToken`. Preserve all returned fields in scope, nulls and `score_state`. Documented fields are not guaranteed for this participant. [WHOOP v2 reference](https://developer.whoop.com/api/)

Cycles are physiological intervals, not fixed calendar days; preserve intervals/offsets before calendar summaries. [WHOOP cycle model](https://developer.whoop.com/docs/developing/user-data/cycle/)

**Continuous heart-rate samples are unavailable through the public API.** Average/max/resting HR are not a continuous series. [WHOOP FAQ](https://developer.whoop.com/docs/developing/support/)

Limits: **100 requests/minute, 10,000/day**, rate-limit headers and HTTP 429. Keep bounded retries inside the daily job; no webhooks/continuous polling. [WHOOP rate limits](https://developer.whoop.com/docs/developing/rate-limiting/)

Thirty days is the requested window; actual history, gaps and scoring/sync delays require measurement. Daily collection adds up to one nominal interval after availability, plus missed-job delays. Ongoing sleep remains provisional at midnight. Unchanged API payloads retain vendor calculations; they are not physical sensor signals.

### Fitbit: existing API access reported; manual fallback available

Export activity, exercise, sleep and heart rate through Google Takeout (select Google Health) for Google login, or the Fitbit account archive procedure for original Fitbit login. Generation is asynchronous; download privately. [Export instructions](https://support.google.com/googlehealth/answer/14236615)

Stage 2 must inspect an authorized export to establish format, units, history and resolution. Preserve selected source files/fields unchanged, label **manual vendor export**, and record import time separately from measurements/archive metadata. Exclude unrelated datasets. Import cadence requires participant action.

Automation requires verifying the existing project's API enablement, OAuth client/callback, linked Google Health profile, user configuration and read-only activity/fitness, sleep and health-metrics scopes. Request offline access; Testing-mode refresh tokens expire after **seven days**, requiring reconnect unless an appropriate published configuration is established. A token failure around one week after setup could be expiration, not loss of project access; no current failure has been reported. Verify identity and a small dataset request before enabling collection. [Google setup](https://developers.google.com/health/setup)

Fitbit Air is listed for HR, sleep and activity. Storage resolution: HR one second, steps one minute; this does not guarantee observed cadence. Verify one-minute HR rollups and a representative original-resolution day with samples. Rollup range caps: 14 days for HR/active minutes/total calories/calories-in-zone, 90 days otherwise; chunk imports accordingly. [Google data types](https://developers.google.com/health/data-types)

Plan the Google collector using stable participant IDs and explicit manual/API provenance, conditional on verified access; reconcile overlaps before activation. Continued access and export/API equivalence remain unverified.

## Free hosting, privacy and spending

Published allowances are verified; actual account plans, remaining allowances and billing controls are **unverified**. Measure capacity with samples.

| Service | Confirmed allowance/limitation | Planned control |
| --- | --- | --- |
| GitHub Actions | GitHub Free: 2,000 standard runner minutes/month, 500 MB artifact allowance shared with Packages; 10 GB cache per repository | Standard Ubuntu runner only; bounded runtime; no health/token artifacts or unnecessary caches. Allowance belongs to the owner and is shared with other usage. [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) |
| Supabase Free | 500 MB database/project, 1 GB file storage, 5 GB egress plus separate 5 GB cached egress; two active Free projects | Choose Free organization; no add-ons/upgrades. Private downloads should budget ordinary egress, not treat cached egress as another private-download allowance. [Supabase pricing](https://supabase.com/pricing) |
| Streamlit Community Cloud | Free hosting connected to private GitHub; one private app per workspace | One small viewer; keep durable data in Supabase. [Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud), [private app limit](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app/indexability) |
| Notion | Existing team documentation workspace | Links, dictionary and findings only; restricted pages. No new plan, health extracts or tokens. |

Before the first job, verify remaining usage and enforce an **Actions product budget of $0 with stop-usage enabled** if a payment method is present. Alerts alone do not block spending. Without a valid payment method, excess usage is blocked. Enable included-usage alerts; budgets are not retroactive. [Budget setup](https://docs.github.com/en/billing/how-tos/set-up-budgets), [behavior](https://docs.github.com/en/billing/concepts/budgets-and-alerts), [billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

Supabase's spend-cap toggle is a **Pro feature**, not a required Free setting: Free usage is not charged, but excess usage can cause restrictions. Do not upgrade to obtain a spend cap. [Cost controls](https://supabase.com/docs/guides/platform/cost-control), [quota restrictions](https://supabase.com/docs/guides/platform/billing-faq)

Proposed Stage 3 thresholds: warn at 70%, stop imports/writes at 80% (350/400 MB database, 700/800 MB files). Include indexes, projected batches and status reserve; deduplicate unchanged payloads by hash. Unknown usage pauses imports. Never delete or upgrade silently. Monitor queries/downloads/backups against monthly egress: warn at 3.5 GB, stop data reads/downloads at 4 GB pending reset/review. Thresholds are proposals, not implemented guarantees.

Above 500 MB, Free databases become read-only. [Database size](https://supabase.com/docs/guides/platform/database-size) Low activity across seven days can cause pausing; daily writes do not guarantee availability. Owner resumes, then collection recovers gaps. [Pausing](https://supabase.com/docs/guides/platform/free-project-pausing) Manually back up both database and Storage files privately; dumps exclude file contents. Test restoration in Stage 3. [Backups](https://supabase.com/docs/guides/platform/backups)

Private Storage enforces access policies on downloads. Prefer fetching bytes through the authorized viewer and serving them in its authenticated session; do not publish public object URLs or bearer signed links in Notion. [Private bucket access](https://supabase.com/docs/guides/storage/buckets/fundamentals)

**Design addition for review:** invited Streamlit viewers can invite others. [Sharing](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app) Add supported OIDC login and a server-side approved-identity allowlist before every query/download. This adds login-client setup without changing hosting. OIDC authenticates; Sentra enforces authorization. Google identity-only access does not require Health API access. Viewer credentials must be read-only, excluding provider tokens in a collector-only durable store. [Streamlit OIDC](https://docs.streamlit.io/develop/concepts/connections/authentication), [Google OIDC](https://developers.google.com/identity/openid-connect/openid-connect)

Streamlit apps sleep after 12 hours without traffic and have resource limits that can change. Visiting can wake them. The viewer cannot host the scheduler or persist the authoritative dataset; paginate tables and bound downloads. [Resources and hibernation](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)

## Midnight scheduling feasibility

Stage 4 can use cron `0 0 * * *` with supported timezone `Asia/Beirut`; DST skipped hours advance to the next valid time. Schedules run only from **main**, requiring a later reviewed merge. Keep development on `ETL-pipeline`. Midnight jobs can be delayed/dropped: show actual execution times and recover gaps next run. [GitHub scheduling](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

## Account and consent checklist (future stages)

- [ ] Both participants agree to named team viewers/downloaders, selected data/original files, hosting, retention and withdrawal/deletion arrangements. OAuth consent alone is insufficient. Keep consent outside Git; follow README supervisor/storage requirements.
- [ ] Friend signs into the WHOOP Developer Dashboard with the existing membership, creates a developer team/app in Sandbox, configures an exact callback URI and app/contact details, and performs the participant OAuth flow. No teammate buys membership. [App setup](https://developer.whoop.com/docs/developing/getting-started/)
- [ ] Request `read:cycles read:recovery read:sleep read:workout` plus `offline`; omit profile and body-measurement scopes initially. Client secrets stay server-side. Refresh invalidates previous WHOOP access and refresh tokens: serialize refresh, securely persist replacements, and reconnect if replacement persistence fails or authorization is revoked. [WHOOP OAuth](https://developer.whoop.com/docs/developing/oauth/)
- [ ] Existing Google project owner identifies which request/action succeeded and confirms current enablement, OAuth publishing status and granted scopes. Do not share secrets, tokens or health payloads in chat. An authorized small data request and refresh demonstration belong to Stage 1 after approval; no new project is required if existing access works.
- [ ] If API access fails, Fitbit participant requests a private export after agreement and provides selected files securely for Stage 2 testing, never through Git or public Notion pages.
- [ ] GitHub owner verifies remaining allowances, Actions permissions, zero-dollar controls and secrets before Stage 4; exclude health data from logs/artifacts.
- [ ] Supabase owner confirms an available Free project slot and Free organization in Stage 3; establishes private storage, collector-only credentials, viewer read-only access and usage monitoring.
- [ ] Streamlit owner confirms a private-app slot and configures private repo access, OIDC/allowlist and secrets in Stage 5.
- [ ] Team names viewers and a private backup location; restricts Notion pages. Decisions remain pending.

## Incremental implementation checklist

| Stage | Next deliverable / acceptance focus |
| --- | --- |
| 1 | Python structure/config; reviewable measurements/sessions/manifests/runs/connection-state schema with vendor units/classification; consent/setup; WHOOP sample and existing Google project sample/refresh checks. Record any genuine blocker and manual fallback. |
| 2 | Paginated/resumable provider imports with bounded history, unchanged compressed payloads and duplicate prevention; Fitbit API collection if verified, otherwise approved export ingestion. |
| 3 | Private Supabase, separate permissions/token store, measured growth/safe stops and backup/restore. |
| 4 | Midnight Beirut schedule, corrections/gap recovery, separate dataset progress, locks and manual triggers; real workflow check. |
| 5 | Private audit viewer/downloads, unauthorized-access checks, coverage/status/quotas and Notion guidance. |
| 6 | Synthetic failures, authorized real comparisons and operating guide with verified/blocked status. |
| 7 | Approved three-day initial daily observation; preliminary audit and supported candidate features; pending until elapsed. See [updated audit plan](stage-7-audit-plan.md). |

Plan amendment, 8 October 2026: the user approved three days instead of the
original two-week observation. Existing history is retained; this is not rolling
retention. The period starts after Stages 4–6 and explicit Stage 7 start approval.
Capacity must be checked before starting; any extension requires further review.

## Checks performed and outstanding evidence

Passed: branch/status/files/history and instructions inspection, read-only GitHub metadata, official provider/hosting/quota/schedule review. No existing code/tests to run. Authentication, export parsing, deployed privacy, billing settings, storage growth and scheduled execution remain untested.

Changes: this report and README participant/milestone/link update only. Use `git diff -- README.md` and open this initially untracked report. Nothing committed or pushed.

Pending: Stage 1/OIDC approval, participant agreement, account owners/viewers and backup location; WHOOP sample, verification of the team's reported Google request/current access/token renewal, actual allowances, private access and growth. Manual Fitbit imports remain a fallback if API access fails.

**Next, after explicit approval:** foundation/schema/setup and small authorized WHOOP/Google requests using available accounts, including Google background-token verification. History import, shared services, workflows and viewer remain later stages.
