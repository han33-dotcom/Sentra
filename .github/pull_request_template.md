Project: Sentra
Task URL:
<!-- Paste the Notion task page URL. Task ID is optional until assigned. -->

## What & why
<!-- One or two lines. Link the issue if there is one: Closes #12 -->

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
