# Wearable audit data dictionary — Notion template

Copy this structure into a private Notion database. Record definitions from official
provider documentation and distinguish them from observed API behavior. Keep
participant agreement, credentials, health files and identifying information out
of this repository. Use participant IDs and private manifest/extract references.

| Property | Meaning / example format |
| --- | --- |
| Provider / dataset | Google Health `daily_steps`; WHOOP `recovery` |
| Vendor metric | Exact returned field / JSON pointer |
| Vendor definition | Meaning and official source link; unknown if unverified |
| Value kind | Measurement, vendor summary, vendor calculation, vendor score, Sentra calculation or unknown |
| Standardized unit / vendor unit | Preserve both; do not infer an undocumented unit |
| Timestamp basis | Physical point, vendor interval, associated cycle interval or vendor civil date |
| Requested resolution | Daily/minute aggregation, original API record or session summary |
| Observed resolution | Sampling interval statistics; distinguish API aggregation from sensor sampling |
| Requested history / observed history | Separate requested range from returned records |
| Availability evidence | Returned, explicit null, unscored, provisional, failed fetch, unsupported with evidence or uncertain |
| Coverage / gaps / corrections | Requested page coverage, observed fields, candidate gaps and change evidence |
| Delivery delay | Observation timestamp minus measurement/interval time where meaningful; pending until observed |
| Source reference | Endpoint, requested range/resolution, private response ID and collection time |
| Candidate feature | Possible derived indicator plus required fields and limitations; not a validated health claim |
| Findings status | Preliminary / pending observation / reviewed; owner and review date |

Initial examples for definition review (not longitudinal findings):

- Google daily step totals are vendor summaries; minutes are separately requested
  aggregation. Counts of fields/records across providers are not directly comparable.
- WHOOP recovery/strain are vendor scores; session heart-rate summaries do not provide
  continuous heart-rate readings. Preserve score state before interpreting absence.
- API originals are unchanged responses, not raw physical sensor signals.

The approved observation is three days. Coverage, arrival delay, correction rates,
storage growth and candidate-feature findings remain **pending** until that period
is explicitly started and the evidence is collected. Two participants on different
devices do not establish population accuracy or validate health predictions.
