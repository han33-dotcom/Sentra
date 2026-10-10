# Readable viewer and ongoing collection implementation plan

**Goal:** Implement the approved private viewer design and an explicit ongoing daily collection control.

**Architecture:** Compute curated daily/session tables from existing audit records without another stored copy. Keep the existing reader, identity checks, original exports, quota guards and collector locks. Explicit ongoing mode supplements the legacy bounded window; publication remains subject to human review.

**Stack:** Existing Python, PostgreSQL/Supabase Free, Streamlit and GitHub Actions.

**Spec:** The approved redesign and ongoing collection request carried into this chat on 10 October 2026.

## Constraints and review focus

- Preserve all source values, units, fields, timestamps, history and original responses.
- No increased collection scope, resolution, frequency, paid resources or health inference.
- Test ongoing/pause validation and preserve legacy bounded-window behavior.
- Test nulls, unscored/provisional values, missing dates, multiple sources and midnight sessions.
- Test WHOOP recovery association by sleep ID, never a guessed date join.
- Readable and audit downloads must clear on selection/identity changes and reauthorize.
- Keep queries bounded; minute data belongs in audit drilldown rather than the overview.
- No commits, pushes, migrations or enabling before the completed change is reviewed.

## Execution

1. Add failing ongoing/pause planner and CLI validation tests; implement the smallest control change. Update obsolete Stage 7 requirements and operating commands.
2. Verify provider definitions from official sources and actual field-name inventory (no health values in logs). Add a provider-specific dictionary and pure curated grouping/formatting tests before implementation.
3. Reuse bounded reader access to load daily/session selections. Add readable summaries, labelled plots, coverage observations and curated downloads; retain audit drilldown and originals. Exercise real Streamlit with synthetic data and private real-data equality checks.
4. Measure repeated record/measurement context and investigate a reversible lossless representation without applying a migration. Record actual measured capacity and equality evidence.
5. Run the full synthetic suite and targeted privacy/live read checks; inspect synthetic UI evidence. Present the revision and proposed commit for approval. After approved publication, recheck free-plan/billing/usage gates and enable with an approved successful run; record exact activation time.

## Evidence ledger

- Preflight: clean `ETL-pipeline`, HEAD `affc0d899a1a9b11994ec9056ee4af5e06f37d9b`; no branch/worktree created.
- 10 October capacity read: database 269,145,779 bytes; originals 657,222 bytes; conservative reserved egress 1,955,385,370 bytes. No provider fetch or control change.
- Execution follows the already approved design inline; additional plan approval and broad brainstorming are unnecessary under the user's explicit instruction. Commit/publication approval remains required.
- Implementation and independent review completed locally. Three reviewer findings reproduced RED→GREEN; full suite 115 tests / zero failures / five opt-in skips; two viewer live tests separately passed. Private source comparison matched 252 mapped values. See [revision evidence and pending gates](viewer-redesign-validation.md).
- Storage experiment reconstructed all 140,727 rows exactly with 29.4% less measured JSONB payload before reference/index overhead; no migration or realized relation-size saving.
- Collection remains disabled in SQL/GitHub. Supabase sign-in, approved code publication (including default `main` for scheduled execution), fresh gates and first approved successful run remain required.
- Follow-up Pinterest reference revision completed locally: presentation/navigation/theme only, with source/export controls retained. Full suite now 117 tests / zero failures / five opt-in skips; synthetic desktop, phone-width and keyboard navigation checked. No commit or publication approval inferred from the design request.
- After explicit user approval, viewer code/tests/theme and the metric-definition dictionary update were committed locally as `f8191aa` (`feat: redesign private wearable explorer`). Collection-control changes remain uncommitted. No push, merge or publication; those remain the next sequential approval step.
- After explicit publication approval, `f8191aa` was pushed to `ETL-pipeline`; the existing private Streamlit viewer redeployed. Fresh allowed Google OIDC, both providers' readable views, readable/audit/original download bytes and original hash, selection clearing and sign-out clearing passed. Publication verified 10 October 2026 12:31:48 UTC; collection remains paused. No `main` merge or operational-code publication.
