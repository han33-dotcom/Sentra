Project: Sentra
Task URL:
<!-- Paste https://github.com/han33-dotcom/Sentra/issues/NUMBER. -->
<!-- Title: [SEN-NUMBER] short description. For multiple implemented tasks, repeat
Additional Task URL: https://github.com/han33-dotcom/Sentra/issues/OTHER_NUMBER
and use [SEN-NUMBER, SEN-OTHER_NUMBER] in the same order. Maximum 10 tasks.
Only declare implementation scope here; put dependencies/references in prose.
Optional Task ID: SEN-NUMBER matches the primary Task URL. -->

## What & why
<!-- One or two lines. Use Related to #12. Do not use Closes/Fixes/Resolves; acceptance controls issue closure. -->

## How tested
- [ ] `python -m pytest` passes from the repository root (live tests skipped unless opted in)
- [ ] Checked against the shared database / providers (say how, with an approved bounded scope), or not needed

## Safety checklist
- [ ] No participant data, original responses, exports, backups, tokens, keys, `.csv`/`.parquet` files or screenshots of real data
- [ ] No change enables scheduled collection (`SENTRA_COLLECTION_ENABLED`, daily-collection control) unless agreed by the team
- [ ] Capacity and egress guards still apply to any new storage or download path
- [ ] Wording stays wellness / fitness-for-shift (no diagnosis, no medical-grade claims)
- [ ] Thresholds changed? Note who approved them (medical expert)
- [ ] Docs updated (`docs/data-dictionary.md`, operating guide) if datasets, metrics or operations changed

## Risks / limitations
<!-- Record relevant limitations; explain if no material risk is identified. -->
