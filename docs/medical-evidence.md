# Evidence Review for Sentra v0 Indicator Rules

**Status:** working evidence brief for the project's medical expert. **Not signed off.**
**Scope:** `src/sentra/processing/thresholds.json` (v0, "pending medical expert sign-off").
**Prepared:** 2026-11-03.

## Purpose and framing

Sentra produces **workplace wellness indicators**, not diagnoses. Its outputs say something like
"your sleep was shorter than recommended" or "this reading is unusual compared with your own recent
history". They never say that a person has, or is at risk of, any medical condition. The literature
below is cited to show **where each v0 threshold comes from and how strong its basis is**. It does
not validate Sentra for any clinical use.

Every threshold stays **provisional until the project's medical expert has reviewed and signed it
off**. The verdicts used below are:

- **SUPPORTS**: the source directly backs the value or method as used.
- **PARTLY SUPPORTS**: the source backs the concept, but the exact number, population or device
  differs, or the evidence is indirect.
- **CONTRADICTS**: the source argues against the value or method.

Each section ends with an "Implication for Sentra" line, which is one of **keep**, **flag for expert
review**, or **weakly supported**.

All citations were checked against PubMed, the publisher, DOAJ or the vendor's documentation on
2026-11-03. Items that could not be fully checked are marked **(unverified)**. Numbers in square
brackets point to the reference list at the end.

---

## 1. Short sleep flag: total sleep < 360 min (6 h)

**Current value:** `short_sleep_minutes: 360`

| Source | What it supports | Verdict |
|---|---|---|
| Watson et al. 2015, AASM/SRS joint consensus [1] | Adults should regularly sleep **7 or more hours** a night for optimal health. Regularly sleeping less than 7 h is associated with adverse health outcomes, impaired performance and more errors and accidents. | PARTLY SUPPORTS: the consensus cut-off is 7 h, so 6 h is a *more lenient* threshold |
| Hirshkowitz et al. 2015, NSF panel [2] | Recommended range for adults (26–64 y) is 7–9 h. The panel lists **6 h as "may be appropriate"** for some adults and **< 6 h as "not recommended"** (band boundaries confirmed via the NSF release table, not the full text). | SUPPORTS: < 6 h is exactly the "not recommended" band |
| Van Dongen et al. 2003 [3] | Two weeks of 6 h time in bed produced cumulative, dose-dependent lapses in alertness and working memory. Participants largely failed to notice their own decline. | SUPPORTS: 6 h is not "enough", and self-perception is unreliable |
| Uehli et al. 2014, meta-analysis [4] | Across 27 studies (n ≈ 268,000), workers with sleep problems had about 1.62× the risk of work injury. Around 13% of work injuries were attributable to sleep problems. | PARTLY SUPPORTS: workplace relevance of poor sleep, though "sleep problems" is broader than duration |

**Notes.** A single short night is common and does not mean much on its own. The evidence above is
about *habitual* or *cumulative* short sleep. Consumer devices measure total sleep time with
reasonable accuracy but are worse at sleep stages (see §12).

**Implication for Sentra:** **keep 360 min as a conservative flag. Flag for expert review:** whether
to (a) add a softer "below 7 h" informational band in line with AASM/SRS, and (b) report a
repeated pattern, such as ≥ 3 short nights in 7, rather than single nights.

---

## 2. Personal baseline: 28-day rolling median + MAD, robust z, |z| ≥ 2, ≥ 7 observations

**Current values:** `baseline_days: 28`, `baseline_min_days: 7`, `z_alert: 2.0`. The baseline
excludes today. z = (x − median) / (1.4826 · MAD).

| Source | What it supports | Verdict |
|---|---|---|
| Leys et al. 2013 [8] | Recommends the median absolute deviation (MAD) over the mean ± SD for detecting outliers. Uses the constant **1.4826** (consistency with SD under normality). Proposes **2.5 × MAD as the default cut-off**, with 3 as stricter and 2 as more lenient (cut-off wording confirmed via secondary sources quoting the paper). | SUPPORTS the method; PARTLY SUPPORTS the cut-off, since 2.0 is more lenient than the recommended 2.5 |
| Plews et al. 2012 [5]; Plews et al. 2013 [6] | Recommend interpreting athlete HRV as **rolling averages against an individual's own baseline** (typically a 7-day rolling mean of ln rMSSD). Also look at day-to-day variation (CV) and the smallest worthwhile change, not single-day values. | SUPPORTS individual baselines; PARTLY SUPPORTS the 28-day window (their smoothing window is 7 days, and baselines run longer) |
| Buchheit 2014 [7] | Review of HR-based monitoring. Changes should be judged against each person's typical variation (smallest worthwhile change / CV), and methodological consistency matters. | SUPPORTS |
| Quer et al. 2020 (PLoS One) [12] | In 92,457 Fitbit users, between-person resting HR (RHR) ranged from about 40 to 109 bpm. Within each person, RHR was much more stable. That makes **within-person** comparison more informative than population norms. | SUPPORTS personal baselines |
| Mishra et al. 2020 [9]; Quer et al. 2021 [10]; Radin et al. 2020 [11] | Large wearable studies flagged deviations of RHR, steps or sleep **from each user's own baseline**. Mishra used residual and outlier methods on personal history. | PARTLY SUPPORTS: these were research or public-health analyses, not workplace alerts |

**Notes.**
- With |z| ≥ 2 and roughly normal data, about 4–5% of ordinary days would be flagged **per metric**.
  With several metrics a day, most people would see an occasional "unusual" flag that means nothing.
  2.0 is more lenient than Leys et al.'s recommended 2.5.
- 7 observations make a fragile median and MAD. A MAD of 0 gives a division by zero, so the code
  must guard it.
- None of the cited studies sets 28 days or 7 days as a standard. These are reasonable engineering
  choices without direct evidence.

**Implication for Sentra:** **keep the method** (median/MAD with personal baseline). **Flag for
expert review:** raise `z_alert` to **2.5**, or require 2 consecutive days at |z| ≥ 2. Consider a
higher `baseline_min_days`, for example 14. Label 28/7 as engineering defaults.

---

## 3. Resting HR above personal baseline (strain, fatigue or illness signal)

**Current rule:** RHR robust z ≥ +2 against the 28-day baseline.

| Source | What it supports | Verdict |
|---|---|---|
| Radin et al. 2020, Lancet Digital Health [11] | Fitbit RHR above each user's own average, combined with sleep, improved state-level estimates of influenza-like illness. | PARTLY SUPPORTS: population-level, not individual alerting |
| Mishra et al. 2020, Nat Biomed Eng [9] | 26 of 32 COVID-19-positive participants showed changes in HR, steps or sleep. Many showed elevated RHR relative to their own baseline, often before symptoms. | PARTLY SUPPORTS: small infected subgroup; research algorithm |
| Quer et al. 2021, Nat Med [10] | Sensor data (including RHR change from baseline) plus symptoms separated COVID-positive from negative symptomatic people (AUC 0.80 vs 0.71 for symptoms alone). | PARTLY SUPPORTS: modest accuracy; illness-specific |
| Quer et al. 2020, PLoS One [12] | RHR is stable within a person. Still, **20% of people had at least one week with a fluctuation of 10 bpm or more**, and RHR varies with season, sleep and age. | PARTLY SUPPORTS, and cautions that normal fluctuations are common |
| Buchheit 2014 [7] | RHR alone is a weaker training-status marker than HRV or submaximal exercise HR. Changes are context-dependent: alcohol, sleep, heat, illness and training all move it. | PARTLY SUPPORTS |

**Implication for Sentra:** **keep, wellness-worded only.** For example: "Your resting heart rate is
higher than your usual range. Rest, hydration, alcohol or illness can all affect this." Never
suggest a cause. **Flag for expert review:** the wording, and whether a persistence requirement
(≥ 2 days) is needed.

---

## 4. Sleeping HR above personal baseline

**Current rule:** sleeping HR robust z ≥ +2 against the 28-day baseline.

| Source | What it supports | Verdict |
|---|---|---|
| Pietilä et al. 2018, JMIR Mental Health [13] | In 4,098 Finnish employees, alcohol intake was dose-dependently associated with **higher HR and lower HRV during the first 3 h of sleep**. Even low intake reduced the HRV-based recovery index. | SUPPORTS: nocturnal HR responds to everyday behaviour in workers |
| Mishra et al. 2020 [9] | Overnight and resting HR elevations relative to personal baseline accompanied infection in many cases. | PARTLY SUPPORTS |
| Shaffer & Ginsberg 2017 [15]; Task Force 1996 [14] | Sleep recordings reduce posture and activity confounds compared with daytime spot readings, so nocturnal metrics are more comparable night to night. | PARTLY SUPPORTS the choice of the sleep window |

**Implication for Sentra:** **keep.** Sleep is the most comparable daily window. **Flag for expert
review:** whether sleeping HR and RHR are redundant on Fitbit (Fitbit RHR is partly derived from sleep
data), and how many of the two can flag on the same day.

---

## 5. HRV (RMSSD) below personal baseline (recovery and stress indicator)

**Current rule:** RMSSD robust z ≤ −2 against the 28-day baseline.

| Source | What it supports | Verdict |
|---|---|---|
| Task Force ESC/NASPE 1996 [14] | Defines RMSSD as a standard time-domain measure of short-term (vagally mediated) variability. Stresses standardised recording conditions. | SUPPORTS choosing RMSSD |
| Shaffer & Ginsberg 2017 [15] | Overview of HRV metrics and norms. RMSSD is the main time-domain index of vagal tone. 24 h, short-term and ultra-short norms are **not interchangeable**, and population norms should be complemented with each person's own data. | SUPPORTS |
| Plews et al. 2012, 2013 [5, 6] | Daily **ln rMSSD**, 7-day rolling mean and its CV tracked maladaptation in elite athletes. A falling trend plus changing variability preceded non-functional overreaching. | SUPPORTS the concept, using log-transformed values and rolling averages |
| Kiviniemi et al. 2007 [16] | RCT: endurance training adjusted daily from morning HRV improved fitness at least as well as predefined training. Supports the use of within-person HRV changes. | PARTLY SUPPORTS (athletic training, not workplace) |
| Kim et al. 2018, review / meta-analysis [17] | Across 37 studies, psychological stress was most often associated with **reduced parasympathetic (HRV) activity**. | SUPPORTS HRV as a stress-*related* indicator |
| Thayer et al. 2012 [18] | Meta-analysis of neuroimaging studies links HRV to prefrontal–amygdala regulation. Proposes HRV as a marker of stress regulation and health. | PARTLY SUPPORTS (mechanistic and theoretical) |

**Notes.** RMSSD is right-skewed, and the literature routinely analyses **ln(RMSSD)** [5, 6, 7].
Median/MAD is fairly robust to skew, but computing z on ln(RMSSD) would align with practice.
Single-day HRV is noisy. The athlete literature interprets 7-day trends.

**Implication for Sentra:** **keep, with changes for expert review.** Compute the baseline on
**ln(RMSSD)**. Consider a 7-day rolling mean compared with the 28-day baseline in addition to, or
instead of, single-day z. **Never mix** Fitbit and WHOOP HRV in one baseline (see §12).

---

## 6. Sustained high HR: HR > 180 − age for ≥ 5 min (default age 30)

**Current values:** `sustained_hr_rule: "hr > 180 - age"`, `sustained_hr_min_minutes: 5`,
`default_age: 30`, which gives a threshold of 150 bpm.

| Source | What it supports | Verdict |
|---|---|---|
| Maffetone "180 Formula" (author's own website) [21] | "180 − age" is the **MAF aerobic training ceiling**, proposed by Phil Maffetone for endurance training. It is not presented as a safety or strain limit. **No peer-reviewed validation was found.** | CONTRADICTS its use here: wrong purpose, not peer-reviewed |
| Tanaka, Monahan & Seals 2001 [19] | Meta-analysis (351 studies, n = 18,712) plus lab validation: **HRmax ≈ 208 − 0.7 × age**. "220 − age" underestimates HRmax in older adults. | PARTLY SUPPORTS an age-based ceiling, but via a different formula |
| Robergs & Landwehr 2002 [20] | The "220 − age" formula (attributed to Fox et al. 1971 [unverified]) has no sound original research basis. Individual HRmax has a large error around any age formula. | CONTRADICTS precise individual use of any age formula |

**Notes.** At age 30, 150 bpm is about 80% of Tanaka-predicted HRmax (187 bpm). Healthy workers
can reach that during stair climbing, manual handling or commuting by bike. In other words, the
rule detects **exertion**, not risk. Wrist PPG is also least accurate during movement (§12). The
default age of 30 misclassifies older and younger staff in opposite directions.

**Implication for Sentra:** **weakly supported. Flag for expert review.** Options: (a) rename it
"sustained high exertion" and phrase it neutrally; (b) replace 180 − age with a **%HRmax from
Tanaka (208 − 0.7 × age)** or with HR reserve using the person's own RHR, so the threshold is
explicit; (c) require a real age and drop the default; (d) exclude periods tagged as exercise.

---

## 7. Long inactivity in shift: ≥ 90 min uninterrupted sitting or stillness

**Current value:** `long_inactivity_minutes: 90` within `shift_window_local` 08:00–18:00.

| Source | What it supports | Verdict |
|---|---|---|
| Healy et al. 2008, Diabetes Care [22] | Cross-sectional (n = 168, accelerometer): more **breaks in sedentary time** were associated with lower waist circumference, BMI and some other metabolic markers, independent of total sedentary time. | SUPPORTS breaking up sitting (no specific interval) |
| Dunstan et al. 2012, Diabetes Care [23] | Randomised crossover: interrupting sitting with **2-min walking bouts every 20 min** lowered post-meal glucose and insulin compared with uninterrupted sitting. | SUPPORTS breaks; suggests much **shorter** intervals than 90 min |
| Buckley et al. 2015, BJSM expert statement [24] | Office workers should progress to **2 h/day, then 4 h/day** of standing and light activity during working hours. Seated work should be **regularly broken up** with standing work. | SUPPORTS the aim; gives no 90-min figure |
| Diaz et al. 2017, Ann Intern Med [25] | Cohort (n = 7,985): longer sedentary bouts were associated with higher mortality. People whose bouts were mostly **< 30 min** had the lowest risk. The authors suggest interrupting sitting about **every 30 min**. | PARTLY SUPPORTS; implies 90 min is lenient |

**Notes.** No consensus document sets a 90-minute alert interval. The evidence points to "break up
sitting often", and 20–30 min is the most specific figure. A wrist device detects *stillness*, not
posture, so standing still reads as sedentary.

**Implication for Sentra:** **keep as a lenient, low-nag default** (90 min avoids alert fatigue).
**Flag for expert review:** whether to tighten to 30–60 min, and how to word it ("consider a short
movement break"). Label it "stillness", not "sitting".

---

## 8. Valid wear day: ≥ 600 min (10 h) wear time

**Current value:** `valid_day_min_wear_minutes: 600`

| Source | What it supports | Verdict |
|---|---|---|
| Troiano et al. 2008, MSSE (NHANES) [26] | Population accelerometer surveillance. Its processing is widely cited as the origin of the **≥ 10 h/day valid-day** criterion, with non-wear defined as ≥ 60 min of zero counts. *The exact wording was confirmed only through secondary NHANES analyses, not the full text.* | SUPPORTS (by convention) |
| Choi et al. 2011, MSSE [27] | Validated an improved wear/non-wear algorithm (90-min window) that reduced misclassification of non-wear time. | PARTLY SUPPORTS: wear detection matters as much as the threshold |
| Migueles et al. 2017, Sports Med, systematic review [28] | Across accelerometer studies, **≥ 10 h/day waking wear** is the most common valid-day rule (often with ≥ 4 valid days). Recommends reporting the criteria explicitly. | SUPPORTS |

**Notes.** These criteria come from research-grade hip accelerometers worn while awake. For a 24-h
wrist wearable that also records sleep, 10 h is lenient. Some 24-h protocols use ≥ 16 h. Fitbit and
WHOOP wear is inferred from HR signal presence, not from accelerometer zero counts.

**Implication for Sentra:** **keep (well-established convention).** **Flag for expert review:**
whether to require a separate "valid night" for sleep-based indicators.

---

## 9. HR valid range: 30–220 bpm

**Current value:** `hr_valid_range_bpm: [30, 220]`

| Source | What it supports | Verdict |
|---|---|---|
| Tanaka et al. 2001 [19] | Predicted HRmax for adults is about 208 − 0.7 × age, which is below 200 for anyone 12 or older. 220 is therefore a generous upper plausibility bound. | PARTLY SUPPORTS the upper bound |
| Quer et al. 2020 [12] | Daily RHR among 92,457 users ranged from about 40 to 109 bpm. A floor of 30 keeps fit or bradycardic users' night values. | PARTLY SUPPORTS the lower bound |
| Task Force 1996 [14] | Artefact and ectopic-beat removal is a prerequisite for valid HR/HRV metrics. | SUPPORTS filtering in principle |

**Notes.** No source found prescribes 30–220 as an artefact filter for consumer wearables. This is a
plausibility rule. Values outside the range are **dropped as artefacts and never surfaced as
alerts**, which keeps the system out of diagnostic territory.

**Implication for Sentra:** **keep as an engineering plausibility filter** (not a health threshold).
**Flag for expert review:** confirm that out-of-range values are discarded silently.

---

## 10. MET thresholds: active ≥ 3.0, sedentary < 1.5

**Current values:** `active_met: 3.0`, `sedentary_met: 1.5`

| Source | What it supports | Verdict |
|---|---|---|
| Ainsworth et al. 2011 Compendium [29] | Standard MET values for activities; 1 MET is resting metabolic rate. Conventional bands are light < 3, moderate 3–5.9, vigorous ≥ 6. | SUPPORTS 3.0 as the moderate threshold |
| Herrmann et al. 2024 Adult Compendium [30] | Third update (1,114 activities, adults 19–59), mostly with measured values. Keeps the same MET framework. | SUPPORTS |
| Tremblay et al. 2017, SBRN consensus [31] | Defines sedentary behaviour as waking behaviour at **≤ 1.5 METs** while sitting, reclining or lying. | SUPPORTS 1.5 (consensus uses ≤ 1.5; Sentra uses < 1.5, a small boundary difference) |

**Notes.** Wrist devices *estimate* METs from acceleration and HR, so error is large at the individual
level. SBRN's definition also requires a posture (sitting/lying), which a wrist device cannot see.

**Implication for Sentra:** **keep.** **Flag for expert review:** align `sedentary_met` to the SBRN
"≤ 1.5" wording and note that posture is not measured.

---

## 11. Group k-anonymity: k = 5 (privacy, not medical)

**Current value:** `cohort_k_anonymity: 5`

| Source | What it supports | Verdict |
|---|---|---|
| Sweeney 2002 [32] | Defines k-anonymity: each released record must be indistinguishable from at least k − 1 others on quasi-identifiers. The paper does not prescribe a specific k. | SUPPORTS the model; k is a policy choice |
| CMS cell-size suppression policy (ResDAC summary) [33] | US Medicare data users may not publish cells with counts of **1–10**. Values derivable from other tables are also prohibited. | PARTLY SUPPORTS; some health-data regimes are **stricter** (≥ 11) |

**Notes.** k = 5 is a common minimum, but health-data regimes often use 10–11. Team-level wellness
aggregates in a small workplace can be re-identified by subtraction across overlapping groups,
which the CMS policy explicitly forbids.

**Implication for Sentra:** **keep as a floor. Flag for privacy/ethics review (not medical):**
consider k ≥ 10 for any health-derived aggregate, and block complementary queries.

---

## 12. Wearable accuracy and validity caveats

| Source | What it supports | Verdict |
|---|---|---|
| de Zambotti et al. 2019, MSSE review [37] | Consumer sleep trackers estimate sleep/wake reasonably but sleep stages poorly. Algorithms are proprietary and change with firmware. | SUPPORTS cautious use |
| Chinoy et al. 2021, Sleep [34] | Seven consumer devices against polysomnography: most matched or beat actigraphy for sleep/wake; sleep-stage accuracy was inconsistent. Includes Fitbit Alta HR. | SUPPORTS total sleep time; cautions on stages |
| Miller et al. 2022, Sensors [35] | Six devices (Apple Watch S6, Garmin FR245, Polar Vantage V, Oura Gen2, **WHOOP 3.0**, Somfit; Fitbit not tested) against PSG/ECG. Valid for sleep timing and duration; sleep stages agreed only about 50–61%. Nocturnal RMSSD agreement ranged from excellent (WHOOP, ICC 0.99) to poor (Garmin, ICC 0.24). | PARTLY SUPPORTS: HRV validity is device-specific |
| Stone et al. 2021, Front Sports Act Living [36] | Seven commercial technologies against ECG: resting HR generally accurate; **RMSSD accuracy varied widely by device** (MAPE about 4% to over 17%). | PARTLY SUPPORTS: HRV is device-dependent |
| Fitbit Web API documentation [38] | Fitbit `dailyRmssd` is RMSSD over the **main (longest) sleep**. It requires ≥ 3 h of sleep and a sleep-stages log, and `deepRmssd` covers deep sleep only. | Context: defines the Fitbit measurement window |
| WHOOP (vendor podcast/blog) [39] | WHOOP's HRV for Recovery is taken during **slow-wave sleep** (the vendor states the last slow-wave period of the night). *No formal WHOOP technical specification was found.* | Context (vendor claim) |

**Implication for Sentra:** **keep, with explicit caveats.** Baselines must be **per person and per
device/vendor**. Fitbit and WHOOP RMSSD use different windows and must not be pooled or compared
directly. Avoid sleep-stage-based indicators in v0. A change of device or firmware should reset the
baseline. **Flag for expert review.**

---

## 13. Missing data must not be presented as reassurance

**Current behaviour:** a baseline needs ≥ 7 of the previous 28 days. Days without valid data produce
no indicator.

| Source | What it supports | Verdict |
|---|---|---|
| Cho et al. 2021, JMIR mHealth uHealth, rapid systematic review [40] | Wearable data quality suffers from non-wear, device and sync failures and lack of standardisation. The result is **incomplete, incorrect and heterogeneous data** that need explicit handling. | SUPPORTS treating missingness explicitly |
| Migueles et al. 2017 [28]; Troiano et al. 2008 [26] | Accelerometer research **excludes** non-valid days and reports wear criteria rather than imputing "normal" values. | SUPPORTS "no data ≠ normal" |

**Notes.** **No direct guideline was found** that says missing wearable data must not be shown as
"all clear", and none sets a 7-of-28-day minimum. That principle is a design and ethics position.
It is consistent with the sources above but not prescribed by them. Missingness in wearables is
often *not random*: people take devices off when ill, travelling or stressed. That makes silent
"green" displays actively misleading.

**Implication for Sentra:** **keep as a design principle.** Show "insufficient data" as a distinct
state, never as green or normal. **Flag for expert review:** the 7-day minimum (no evidence base).

---

## Summary of verdicts

| # | Rule | Value | Overall | Action |
|---|---|---|---|---|
| 1 | Short sleep | < 360 min | Supported (lenient vs 7 h consensus) | Keep; review 7 h band |
| 2 | Baseline method | 28 d median/MAD, ≥ 7 obs, \|z\| ≥ 2 | Method supported; cut-off lenient | Review z = 2.5 / persistence |
| 3 | RHR above baseline | z ≥ +2 | Partly supported | Keep, wellness wording |
| 4 | Sleeping HR above baseline | z ≥ +2 | Supported | Keep; check redundancy with RHR |
| 5 | HRV below baseline | z ≤ −2 | Supported (concept) | Use ln(RMSSD), trends |
| 6 | Sustained high HR | > 180 − age, ≥ 5 min | **Weakly supported** | Replace or rename |
| 7 | Long inactivity | ≥ 90 min | Partly supported (lenient) | Review 30–60 min |
| 8 | Valid wear day | ≥ 600 min | Supported (convention) | Keep |
| 9 | HR valid range | 30–220 bpm | Engineering plausibility | Keep as filter |
| 10 | MET bands | ≥ 3.0 / < 1.5 | Supported | Align to ≤ 1.5 |
| 11 | k-anonymity | 5 | Policy choice | Privacy review (k ≥ 10?) |
| 12 | Device validity | n/a | Caveats apply | Per-device baselines |
| 13 | Missing data | ≥ 7/28 days | No direct guideline | Keep principle; review 7 |

---

## References

Style: Authors. Title. *Journal*. Year;Vol(Issue):pages. DOI / PMID.

1. Watson NF, Badr MS, Belenky G, et al. Recommended amount of sleep for a healthy adult: a joint consensus statement of the American Academy of Sleep Medicine and Sleep Research Society. *J Clin Sleep Med*. 2015;11(6):591–592. https://doi.org/10.5664/jcsm.4758 · PMID [25979105](https://pubmed.ncbi.nlm.nih.gov/25979105/)
2. Hirshkowitz M, Whiton K, Albert SM, et al. National Sleep Foundation's sleep time duration recommendations: methodology and results summary. *Sleep Health*. 2015;1(1):40–43. https://doi.org/10.1016/j.sleh.2014.12.010 · PMID [29073412](https://pubmed.ncbi.nlm.nih.gov/29073412/)
3. Van Dongen HPA, Maislin G, Mullington JM, Dinges DF. The cumulative cost of additional wakefulness: dose-response effects on neurobehavioral functions and sleep physiology from chronic sleep restriction and total sleep deprivation. *Sleep*. 2003;26(2):117–126. https://doi.org/10.1093/sleep/26.2.117 · PMID [12683469](https://pubmed.ncbi.nlm.nih.gov/12683469/)
4. Uehli K, Mehta AJ, Miedinger D, et al. Sleep problems and work injuries: a systematic review and meta-analysis. *Sleep Med Rev*. 2014;18(1):61–73. https://doi.org/10.1016/j.smrv.2013.01.004 · PMID [23702220](https://pubmed.ncbi.nlm.nih.gov/23702220/)
5. Plews DJ, Laursen PB, Kilding AE, Buchheit M. Heart rate variability in elite triathletes, is variation in variability the key to effective training? A case comparison. *Eur J Appl Physiol*. 2012;112(11):3729–3741. https://doi.org/10.1007/s00421-012-2354-4 · PMID [22367011](https://pubmed.ncbi.nlm.nih.gov/22367011/)
6. Plews DJ, Laursen PB, Stanley J, Kilding AE, Buchheit M. Training adaptation and heart rate variability in elite endurance athletes: opening the door to effective monitoring. *Sports Med*. 2013;43(9):773–781. https://doi.org/10.1007/s40279-013-0071-8
7. Buchheit M. Monitoring training status with HR measures: do all roads lead to Rome? *Front Physiol*. 2014;5:73. https://doi.org/10.3389/fphys.2014.00073 · PMID [24578692](https://pubmed.ncbi.nlm.nih.gov/24578692/)
8. Leys C, Ley C, Klein O, Bernard P, Licata L. Detecting outliers: do not use standard deviation around the mean, use absolute deviation around the median. *J Exp Soc Psychol*. 2013;49(4):764–766. https://doi.org/10.1016/j.jesp.2013.03.013
9. Mishra T, Wang M, Metwally AA, et al. Pre-symptomatic detection of COVID-19 from smartwatch data. *Nat Biomed Eng*. 2020;4(12):1208–1220. https://doi.org/10.1038/s41551-020-00640-6 · PMID [33208926](https://pubmed.ncbi.nlm.nih.gov/33208926/)
10. Quer G, Radin JM, Gadaleta M, et al. Wearable sensor data and self-reported symptoms for COVID-19 detection. *Nat Med*. 2021;27(1):73–77. https://doi.org/10.1038/s41591-020-1123-x
11. Radin JM, Wineinger NE, Topol EJ, Steinhubl SR. Harnessing wearable device data to improve state-level real-time surveillance of influenza-like illness in the USA: a population-based study. *Lancet Digit Health*. 2020;2(2):e85–e93. https://doi.org/10.1016/S2589-7500(19)30222-5
12. Quer G, Gouda P, Galarnyk M, Topol EJ, Steinhubl SR. Inter- and intraindividual variability in daily resting heart rate and its associations with age, sex, sleep, BMI, and time of year: retrospective, longitudinal cohort study of 92,457 adults. *PLoS One*. 2020;15(2):e0227709. https://doi.org/10.1371/journal.pone.0227709 · PMID [32023264](https://pubmed.ncbi.nlm.nih.gov/32023264/)
13. Pietilä J, Helander E, Korhonen I, Myllymäki T, Kujala UM, Lindholm H. Acute effect of alcohol intake on cardiovascular autonomic regulation during the first hours of sleep in a large real-world sample of Finnish employees: observational study. *JMIR Ment Health*. 2018;5(1):e23. https://doi.org/10.2196/mental.9519 · PMID [29549064](https://pubmed.ncbi.nlm.nih.gov/29549064/)
14. Task Force of the European Society of Cardiology and the North American Society of Pacing and Electrophysiology. Heart rate variability: standards of measurement, physiological interpretation and clinical use. *Circulation*. 1996;93(5):1043–1065. https://doi.org/10.1161/01.CIR.93.5.1043 · PMID [8598068](https://pubmed.ncbi.nlm.nih.gov/8598068/)
15. Shaffer F, Ginsberg JP. An overview of heart rate variability metrics and norms. *Front Public Health*. 2017;5:258. https://doi.org/10.3389/fpubh.2017.00258 · PMID [29034226](https://pubmed.ncbi.nlm.nih.gov/29034226/)
16. Kiviniemi AM, Hautala AJ, Kinnunen H, Tulppo MP. Endurance training guided individually by daily heart rate variability measurements. *Eur J Appl Physiol*. 2007;101(6):743–751. https://doi.org/10.1007/s00421-007-0552-2 · PMID [17849143](https://pubmed.ncbi.nlm.nih.gov/17849143/)
17. Kim HG, Cheon EJ, Bai DS, Lee YH, Koo BH. Stress and heart rate variability: a meta-analysis and review of the literature. *Psychiatry Investig*. 2018;15(3):235–245. https://doi.org/10.30773/pi.2017.08.17 · PMID [29486547](https://pubmed.ncbi.nlm.nih.gov/29486547/)
18. Thayer JF, Åhs F, Fredrikson M, Sollers JJ, Wager TD. A meta-analysis of heart rate variability and neuroimaging studies: implications for heart rate variability as a marker of stress and health. *Neurosci Biobehav Rev*. 2012;36(2):747–756. https://doi.org/10.1016/j.neubiorev.2011.11.009 · PMID [22178086](https://pubmed.ncbi.nlm.nih.gov/22178086/)
19. Tanaka H, Monahan KD, Seals DR. Age-predicted maximal heart rate revisited. *J Am Coll Cardiol*. 2001;37(1):153–156. https://doi.org/10.1016/S0735-1097(00)01054-8 · PMID [11153730](https://pubmed.ncbi.nlm.nih.gov/11153730/)
20. Robergs RA, Landwehr R. The surprising history of the "HRmax = 220 − age" equation. *J Exerc Physiol Online*. 2002;5(2):1–10. (No DOI; bibliographic details confirmed via citing literature.)
21. Maffetone P. The 180 Formula / MAF method. Author's website (not peer-reviewed). https://philmaffetone.com/the-180-review
22. Healy GN, Dunstan DW, Salmon J, et al. Breaks in sedentary time: beneficial associations with metabolic risk. *Diabetes Care*. 2008;31(4):661–666. https://doi.org/10.2337/dc07-2046 · PMID [18252901](https://pubmed.ncbi.nlm.nih.gov/18252901/)
23. Dunstan DW, Kingwell BA, Larsen R, et al. Breaking up prolonged sitting reduces postprandial glucose and insulin responses. *Diabetes Care*. 2012;35(5):976–983. https://doi.org/10.2337/dc11-1931 · PMID [22374636](https://pubmed.ncbi.nlm.nih.gov/22374636/)
24. Buckley JP, Hedge A, Yates T, et al. The sedentary office: an expert statement on the growing case for change towards better health and productivity. *Br J Sports Med*. 2015;49(21):1357–1362. https://doi.org/10.1136/bjsports-2015-094618
25. Diaz KM, Howard VJ, Hutto B, et al. Patterns of sedentary behavior and mortality in U.S. middle-aged and older adults: a national cohort study. *Ann Intern Med*. 2017;167(7):465–475. https://doi.org/10.7326/M17-0212
26. Troiano RP, Berrigan D, Dodd KW, Mâsse LC, Tilert T, McDowell M. Physical activity in the United States measured by accelerometer. *Med Sci Sports Exerc*. 2008;40(1):181–188. https://doi.org/10.1249/mss.0b013e31815a51b3 · PMID [18091006](https://pubmed.ncbi.nlm.nih.gov/18091006/) (≥ 10 h valid-day wording confirmed via secondary sources only)
27. Choi L, Liu Z, Matthews CE, Buchowski MS. Validation of accelerometer wear and nonwear time classification algorithm. *Med Sci Sports Exerc*. 2011;43(2):357–364. https://doi.org/10.1249/MSS.0b013e3181ed61a3 · [PMC3184184](https://pmc.ncbi.nlm.nih.gov/articles/PMC3184184)
28. Migueles JH, Cadenas-Sanchez C, Ekelund U, et al. Accelerometer data collection and processing criteria to assess physical activity and other outcomes: a systematic review and practical considerations. *Sports Med*. 2017;47(9):1821–1845. https://doi.org/10.1007/s40279-017-0716-0 · PMID [28303543](https://pubmed.ncbi.nlm.nih.gov/28303543/)
29. Ainsworth BE, Haskell WL, Herrmann SD, et al. 2011 Compendium of Physical Activities: a second update of codes and MET values. *Med Sci Sports Exerc*. 2011;43(8):1575–1581. https://doi.org/10.1249/MSS.0b013e31821ece12 · PMID [21681120](https://pubmed.ncbi.nlm.nih.gov/21681120/)
30. Herrmann SD, Willis EA, Ainsworth BE, et al. 2024 Adult Compendium of Physical Activities: a third update of the energy costs of human activities. *J Sport Health Sci*. 2024;13(1):6–12. https://doi.org/10.1016/j.jshs.2023.10.010 · PMID [38242596](https://pubmed.ncbi.nlm.nih.gov/38242596/)
31. Tremblay MS, Aubert S, Barnes JD, et al. Sedentary Behavior Research Network (SBRN) – Terminology Consensus Project process and outcome. *Int J Behav Nutr Phys Act*. 2017;14:75. https://doi.org/10.1186/s12966-017-0525-8 · PMID [28599680](https://pubmed.ncbi.nlm.nih.gov/28599680/)
32. Sweeney L. k-anonymity: a model for protecting privacy. *Int J Uncertain Fuzziness Knowl-Based Syst*. 2002;10(5):557–570. https://doi.org/10.1142/S0218488502001648
33. Research Data Assistance Center (ResDAC). CMS cell size suppression policy (summary). https://resdac.org/node/1506 (secondary summary of the CMS policy; the primary CMS document was not retrieved)
34. Chinoy ED, Cuellar JA, Huwa KE, et al. Performance of seven consumer sleep-tracking devices compared with polysomnography. *Sleep*. 2021;44(5):zsaa291. https://doi.org/10.1093/sleep/zsaa291 · PMID [33378539](https://pubmed.ncbi.nlm.nih.gov/33378539/)
35. Miller DJ, Sargent C, Roach GD. A validation of six wearable devices for estimating sleep, heart rate and heart rate variability in healthy adults. *Sensors*. 2022;22(16):6317. https://doi.org/10.3390/s22166317 · PMID [36016077](https://pubmed.ncbi.nlm.nih.gov/36016077/)
36. Stone JD, Ulman HK, Tran K, et al. Assessing the accuracy of popular commercial technologies that measure resting heart rate and heart rate variability. *Front Sports Act Living*. 2021;3:585870. https://doi.org/10.3389/fspor.2021.585870 · PMID [33733234](https://pubmed.ncbi.nlm.nih.gov/33733234/)
37. de Zambotti M, Cellini N, Goldstone A, Colrain IM, Baker FC. Wearable sleep technology in clinical and research settings. *Med Sci Sports Exerc*. 2019;51(7):1538–1557. https://doi.org/10.1249/MSS.0000000000001947 · PMID [30789439](https://pubmed.ncbi.nlm.nih.gov/30789439/)
38. Fitbit / Google. Web API reference: Get HRV Summary by Date. https://dev.fitbit.com/build/reference/web-api/heartrate-variability/get-hrv-summary-by-date/ (accessed 2026-11-03)
39. WHOOP. HRV insights compilation (The Locker, podcast 133). https://www.whoop.com/eu/en/thelocker/podcast-133-hrv-insights-compilation (vendor statement; the "last slow-wave sleep" window was not found in a formal technical specification)
40. Cho S, Ensari I, Weng C, Kahn MG, Natarajan K. Factors affecting the quality of person-generated wearable device data and associated challenges: rapid systematic review. *JMIR Mhealth Uhealth*. 2021;9(3):e20738. https://doi.org/10.2196/20738 · PMID [33739294](https://pubmed.ncbi.nlm.nih.gov/33739294/)

**Mentioned but not independently verified:** Fox SM, Naughton JP, Haskell WL. *Ann Clin Res*. 1971
(the commonly cited origin of "220 − age") **(unverified)**.
