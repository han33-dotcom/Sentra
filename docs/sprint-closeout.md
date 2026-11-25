# November wearable sprint closeout

On November 26, 2026 the team verified the private dashboard using stored readings through November 24. Regular collection is paused and the scheduled follow-ups were canceled. Another collection or dashboard refresh needs its own approval. The remaining planning task is [SEN-154](https://github.com/han33-dotcom/Sentra/issues/154).

## What the ten participants contributed

| November 23–24 in Beirut | Fitbit | WHOOP |
| --- | ---: | ---: |
| Consenting people with a connected device and usable readings on at least one date | 5 | 5 |
| People with a recent day on the refreshed dashboard | 5 | 4 |
| People with enough earlier readings for at least one recent personal baseline | 1 | 0 |
| People with a complete recent wellness assessment | 1 | 0 |

Nine people contributed readings on both dates. A device can return readings even when the dashboard lacks the inputs to display a day or assess it. The team verified the dashboard publication, eligibility update, demonstration consent filter and small-group privacy rule. [Recruitment](https://github.com/han33-dotcom/Sentra/issues/38#issuecomment-7174441747) · [Collection](https://github.com/han33-dotcom/Sentra/issues/47#issuecomment-7174447578) · [Dashboard and demonstration](https://github.com/han33-dotcom/Sentra/issues/43#issuecomment-7175922384)

## How much transfer the runs used

These figures are decimal MB reserved against Sentra’s shared transfer allowance. The Supabase Pro plan is intentional. The monthly stop is 4.5 GB, with no additional spend.

| Operation | Reserved | What was verified |
| --- | ---: | --- |
| Three scheduled days, November 20–22, one Fitbit | 46.2 MB | All 36 requests returned records. Database usage grew by 991,232 bytes. |
| Replay on the original Fitbit after the accounting fix | 4.65 MB | Twelve requests fit the 5 MB target. |
| Two-person trial, November 23–24 readings | 11.85 MB of 30 MB | Eight Fitbit requests used 6.51 MB and six WHOOP requests used 5.05 MB. Shared checks account for the balance. |
| Remaining eight people after the two-person trial | 46.38 MB of 60 MB | Four Fitbit accounts used 26.05 MB, four WHOOP accounts used 19.26 MB, and shared checks used 1.06 MB. |
| Stopped dashboard attempts and sizing | 99.50 MB of 100 MB | The previous publication remained available. |
| Successful dashboard retry, including verification | 64.60 MB of 70 MB | The published data matched the stored source and tier hashes. |

Dashboard work across both allowances reserved 164,099,030 bytes. At final verification, 79,229,656 bytes remained below the November stop. This is a dated balance. The refresh used existing readings and incurred no additional spend. [Pilot](https://github.com/han33-dotcom/Sentra/issues/47#issuecomment-7082970861) · [Replay](https://github.com/han33-dotcom/Sentra/issues/50#issuecomment-7169451906) · [Batch measurements](https://github.com/han33-dotcom/Sentra/issues/50#issuecomment-7173893213) · [Final accounting](https://github.com/han33-dotcom/Sentra/issues/50#issuecomment-7175918152)

## What remains unmeasured

Repeated daily collection was demonstrated for one Fitbit. The team deferred full-group daily reliability and recurring transfer cost. The imports and refresh do not establish a daily budget for ten or a forecast for 100 people. Wellness thresholds remain provisional pending expert review. [Collection decision](https://github.com/han33-dotcom/Sentra/issues/47#issuecomment-7174447578) · [Indicator contract](indicator-contract.md)
