# Collection restart readiness

Task: [#44](https://github.com/han33-dotcom/Sentra/issues/44). Owner:
`han33-dotcom`; human reviewer: `MohamadNasrallah`. This is the current restart
ledger, separate from October's historical acceptance in the stage guides.

**November 3, 2026 decision: blocked; collection remains paused.** Stored
authorization needs attention, provider-dashboard and dependent team evidence
are incomplete, and forward/catch-up windows have not been agreed.
Neither this document nor a successful inspection authorizes collection.

## Repeatable inspection

From the authorized operator checkout, with Python 3.11 and ignored local setup:

```powershell
.venv/Scripts/python.exe -m sentra.cli cloud-readiness
```

This reads usage, the SQL collection control and explicitly configured encrypted
cloud connection metadata. It never calls provider APIs, refreshes a token,
downloads health rows/originals, changes consent or collection controls, or
creates a collection job. Existing conservative egress reservations still apply:
the inspection is not free of transfer usage. Missing/stale/exhausted budget or
storage capacity stops further inspection; there is no quota bypass.

The command prints aggregate states and infrastructure usage. Participant-specific
results are encrypted with the existing local OS-vault key in
`.private/readiness/latest.enc`. Treat this file as private operator evidence;
do not upload it, its decrypted contents or credentials to GitHub. Each run
replaces the latest report; retain dated encrypted copies privately when needed.

Exit 1 means an inspected technical blocker. Exit 0 means inspected metadata did
not reveal a technical blocker and the decision is `operator_review_required`;
it does **not** mean restart approved or live authorization demonstrated. An
expired access token with an unexpired stored refresh authorization is
`refresh_needed`, not proof the refresh will work. Provider-side revocation and
dashboard changes remain unknown until appropriately authorized verification.

The scope is the local cloud setup's explicit connections, including provider
lists once #28 supplies them. This is not an enrollment census or a check of
#28's opt-in enrolled-connection discovery. It does not compare secret values
with GitHub Actions or prove deployed code/configuration matches the checkout.
Do not use it to claim five connected, contributing or assessable participants.

## November 3 observations

Bounded inspection at approximately **16:06 UTC / 18:06 Asia/Beirut**:

| Check | Observed result | Limit of evidence |
| --- | --- | --- |
| Local shared setup | Repaired stale certificate paths after the checkout moved; matched the certificate against encrypted cloud setup and preserved encrypted originals | No keys rotated, cloud secrets replaced or migrations applied |
| Database usage | 310,310,579 bytes (310.3 decimal MB) | About 69.7 MB remains before the 380 MB import stop, before estimating the next batch |
| Original objects | 4,037,875 bytes (4.0 MB) | Does not establish database growth capacity |
| Conservative monthly egress | 1,070,505,702 bytes (1.071 GB), before this inspection's metadata reservation | Reservations plus a verified baseline, not a billing meter; other organization clients are not measured here |
| Budget guard | Current bounded status/metadata reads and growth report permitted | Does not replace a current signed-in organization usage/Free-plan check |
| SQL control | `paused` | Point-in-time read; inspection does not change it |
| GitHub schedule variable | `SENTRA_COLLECTION_ENABLED=false`, independently read through authenticated repository API | No dispatch or scheduled run started |
| GitHub zero-spend variable | `SENTRA_ZERO_SPEND_CONFIRMED=true` | Historical confirmation flag, not a fresh billing/dashboard verification |
| Stored authorization | Reconnect/refresh work remains; detailed results retained encrypted privately | No provider token request or health request made; no live renewal demonstrated |
| Growth evidence | Existing `growth_report()` executed; result encrypted privately in `.private/readiness/growth.enc` | Historical requested-day averages include gaps and are not a five-participant capacity forecast |

Signed-in dashboards subsequently checked at approximately **16:12–16:16 UTC /
18:12–18:16 Asia/Beirut**:

| Dashboard | Observed result | Interpretation |
| --- | --- | --- |
| GitHub billing overview | GitHub Free; Actions billable usage $0; included compute $0 used / $12 included; Actions storage 0 GB / 0.5 GB | Current UI uses a monetary compute allowance; do not substitute the stage guide's historical runner-minute presentation |
| GitHub budgets | Account-wide Actions $0 budget; status **Usage blocked** | Spending is stopped at the budget; no budget, subscription or payment setting changed |
| Supabase billing | **Free Plan**, **Spend cap is enabled** | Organization remains limited by included usage |
| Supabase organization usage | Cycle **October 8–November 8, 2026**; no quota exceeded; database **0.325 / 0.5 GB**; uncached egress **0.885 / 5 GB**; Storage **0.002 / 1 GB** | Rounded dashboard values; usage can lag up to an hour. This billing cycle differs from the collector's UTC-month reservation ledger |

The dashboard's rounded database figure is larger than the direct SQL usage
snapshot above. Keep both measurements and ask #50 to reconcile their timing and
accounting scope; plan conservatively against the larger figure (about **55 MB**
below the existing 380 MB import stop), rather than promising 69.7 MB of usable
growth. The dashboard's object figure also differs from the collector's source
manifest accounting. Neither difference authorizes deleting history or changing
limits. Preserve the current egress baseline and reservations; no baseline was
rewritten to align the two different periods. Sanitized operator observations
are retained encrypted in `.private/readiness/operator-metadata.enc`.

The October database/egress figures in the stage guides are historical. Do not
substitute them for this observation or interpret the November UTC-month ledger
as the platform's billing-period meter. No egress baseline/reservations were reset.

The current [storage plan](storage-plan.md) keeps daily collection paused until
its verified compaction/approval gate is satisfied. Current headroom alone does
not override that decision. Nasrallah owns measured growth, capacity, retention,
backup, recovery and compaction evidence (#29, #30, #46, #50); consume that work
without duplicating or performing its destructive steps under #44.

## Provider readiness

Primary vendor documentation checked November 3, 2026. Published defaults are
planning inputs; record the actual configured client/project limits privately.
The signed-in Google Cloud project opened, but its Audience page returned
**Failed to load**; current audience/publication/test-user settings could not be
read. WHOOP's developer portal redirected to sign-in. No provider setting or
participant authorization was changed in either attempt.

- **Google Health:** the operator configuration says `testing`. Google's
  [refresh-token rules](https://developers.google.com/identity/protocols/oauth2#expiration)
  give external Testing clients seven-day refresh authorization, except identity-only
  scopes. Sentra requests health scopes, so that exception does not apply. Renewing
  an access token does not extend the original Testing period. The stored check
  found expired authorization; do not try repeated refreshes to repair it.
- Proposed sprint approach: retain Testing for the bounded pilot, verify each
  intended test user in the console, and arrange participant-driven reconnection
  before each seven-day expiry. This requires team agreement and must be reported
  as an interruption dependency. Production/verification is separate work, not an
  automatic publishing change or a guarantee of permanent authorization.
- Google's published [Health API limits](https://developers.google.com/health/rate-limits)
  include 300 requests/minute/user and project-level limits. Verify actual project
  quota and enabled health scopes before a run; the Google Health API is distinct
  from Cloud Healthcare API. Keep bounded retries/backoff and do not request increases.
- **WHOOP:** [refreshing replaces the access and refresh tokens](https://developer.whoop.com/docs/developing/oauth/).
  Keep serialized cloud ownership and durable replacement; never refresh an old
  laptop token copy. Stored access expiry requires a future authorized renewal;
  its outcome is currently unverified. Ambiguous rotation requires reconnect.
- WHOOP's published [Sandbox tier](https://developer.whoop.com/docs/developing/app-approval/)
  allows up to ten members. Verify the actual app tier, occupied seats and callback
  registration privately; the published limit does not prove seats are available.
  Default [rate limits](https://developer.whoop.com/docs/developing/rate-limiting/)
  are 100 requests/minute and 10,000/day per client. The existing 0.65-second
  pacing is about 92 requests/minute for one sequential client; it is not a shared
  quota meter for multiple processes or applications. Preserve writer/refresh locks,
  bounded request windows and 429 handling.

For legacy cloud-owned connections, reconnect only through the affected
`cloud-connect PROVIDER --reauthorize` path in the operating guide. For #28's
enrolled connections, use its reviewed, deployed participant account/reconnect
flow. PR #52 merged into `develop` during this work and was integrated into this
branch before final checks. That merge is not a hosted deployment. Do not
silently relink identities, copy credentials between participants,
or make enrollment enable collection. #28's deployment/provider prerequisites
remain separate from the synthetic implementation evidence in PR #52.

## Proposed windows, awaiting agreement

1. **Forward collection:** start from the agreed restart date in Asia/Beirut,
   after all gates below. Normal daily collection revisits the prior three days
   and uses per-dataset coverage. Late data stays provisional; success does not
   prove uninterrupted measurements. Keep `activity-level` on explicit request
   and original-resolution heart rate out of the daily plan.
2. **First verification:** one existing supported connection and one complete
   past Beirut day, starting with the smallest supported dataset (Google
   `daily_steps`, or an explicitly selected WHOOP dataset). As of this inspection,
   the candidate interval is November 2 inclusive through November 3 exclusive.
   Recalculate the candidate day if approval occurs later. Select the exact
   participant privately, estimate the next batch and check budget first.
3. **Catch-up:** do not automatically request the whole paused interval. Agree
   exact participant/provider/dataset dates and estimated storage/transfer cost;
   begin with at most one past day per bounded verification batch, inspect the
   result and remaining allowance, then decide the next batch. The existing CLI
   ceiling of 30 past days is a validation bound, not permission to fetch 30 days.
   Larger gaps need separately agreed bounded recovery. Do not repeat the full
   initial import or include on-request dense datasets by default.
4. **Scale/observation:** begin #47's repeated daily observation after readiness
   and authorization; add #38's consenting participants in small batches using
   #28. Log per-participant interruptions, reconnects, actual measurements and
   recovery privately. Count connected, contributing and assessable separately.

No dates, reconnects, health requests, workflow dispatches or activation commands
in this proposal have been approved or executed by this readiness work.

## Outstanding restart gates

- [x] Fresh signed-in Supabase Free/organization database, objects and uncached
  egress check; current bounded budget reservations permitted. Reverify at least
  weekly, each new UTC month and before operation if stale. Preserve reservations,
  thresholds and next-batch estimates; reconcile dashboard accounting under #50.
- [x] Fresh account-wide GitHub Free/Actions allowance and **$0 budget / Usage
  blocked** check. A repository variable alone was not used as this evidence.
- [ ] Actual provider dashboard quotas, test-user/tier availability, scope and
  callback settings checked; affected authorization reconnected/renewed with
  consent and private evidence. Agree the Google Testing reconnection approach.
- [ ] Participation/approval readiness from Abolhoda (#26/#27); current consent
  and withdrawal respected. A local `agreed` flag is not new sprint approval.
- [ ] Nasrallah's capacity and verified retention/backup/recovery/storage evidence
  (#29/#30/#46/#50), including the storage plan's restart gate.
- [ ] Reviewed deployment/configuration and #28/#47 prerequisites verified;
  synthetic CI results do not prove hosted or real-device operation.
- [ ] Team/operator records exact forward/catch-up scope, allowed first batch and
  explicit restart authorization. Keep both controls paused until this is satisfied.
- [ ] MohamadNasrallah verifies #44 acceptance. Keep the issue open until then.

Record any future enabling time and first successful approved run separately in
#47's private evidence. Never mark #44 Done based solely on this report or its PR.

## Implementation validation

After integrating PR #52 from current `develop`:

- `.venv/Scripts/python.exe -m pytest -ra`: **259 passed, 25 skipped**. Skips
  comprise five existing live checks, four opt-in organization-database checks
  and sixteen isolated enrollment-PostgreSQL checks. One existing Starlette/httpx
  deprecation warning remains. No live-test opt-in was enabled.
- Nineteen synthetic readiness cases cover expiry/Testing deadlines, pending and
  withdrawn connections, missing scopes, invalid metadata, identity mismatch,
  stale budget/capacity stops, paused controls, bounded inspection, aggregate
  output and encrypted private evidence without HTTP or credential mutation.
- `python scripts/check_no_data.py`, `node --test tests/test_board_chart.cjs`
  (three passed), `python -m pip check` and `git diff --check`: passed using the
  prepared environment.
- Final `cloud-readiness` run at **16:18 UTC / 18:18 Asia/Beirut** returned
  **blocked** (expected exit 1), SQL paused, zero provider requests and unchanged
  database/object usage. Its conservative egress snapshot was 1,070,964,454 bytes
  before reserving metadata allowance. Provider status details remain encrypted.

Remote CI and independent human review are separate evidence. These checks do
not exercise live refresh/OAuth, a collection run, a hosted deployment, five
participants, backup/restore, compaction or an approved restart.

### Review correction: stored OAuth client fields

MohamadNasrallah identified that absent OAuth client fields could incorrectly
pass inspection. The check now treats missing, null, empty, whitespace-only or
non-string `client_id`/`client_secret` as `credential_metadata_invalid`, blocking
inspection for both current and expired access tokens. Regression tests use a
complete valid connection fixture, check both fields and keep credential values
out of reports. Valid Google Health and WHOOP connections retain their expected
`access_current`/`refresh_needed` states. No renewal or provider request is needed
to detect this local metadata defect.

Review-fix validation: the new regression reproduced the incorrect ready result
before the fix. Afterward, `python -m pytest tests/test_readiness.py -q` passed
all 42 cases; `python -m pytest -ra` passed 282 with the same 25 opt-in skips.
The data guard, three board JavaScript checks and diff checks also passed.
