# Retention and Backup Policy: Evidence Base

Sentra collects consumer wearable data (Fitbit via the Google Health API, and WHOOP) from a small number of consenting adult volunteers to build workplace wellness indicators. It is a final-year research project at the American University of Beirut (AUB), and it is not a clinical trial.

The data held is:

- daily summaries (sleep, resting HR, HRV)
- minute- and second-level heart-rate series
- original API responses, compressed and hashed
- consent history

It is stored in Supabase Postgres (free tier), in private object storage, and in compressed Parquet archives.

**This is not legal advice.** This file collects sources a retention and backup policy can cite. The team, the faculty advisor and the AUB IRB decide the actual periods and controls. GDPR and HIPAA are included as reference standards. Neither is assumed to apply to Sentra directly. Where a claim could not be checked against the source, it is marked **(unverified)**.

Checked on 2026-11-03. The numbers in brackets refer to the reference list at the end.

---

## 1. Data protection principles (GDPR / UK GDPR)

| Source | What it says | How it applies to Sentra |
|---|---|---|
| GDPR Art. 5(1)(c), data minimisation [1][2] | Personal data must be adequate, relevant and limited to what is necessary for the purpose. | Collect only the metrics the indicators need. Justify keeping second-level HR series when daily summaries may be enough. |
| GDPR Art. 5(1)(e), storage limitation [1][2] | Data must be kept in identifiable form no longer than necessary. Longer storage is allowed for scientific research or statistics under Art. 89(1), with safeguards. | Every data class needs a stated retention period with a reason. A research purpose can justify longer retention only if safeguards are in place. |
| GDPR Art. 9(1), 9(2)(a), 9(2)(j) [1][3] | Health data is a special category and processing it is prohibited by default. Exceptions include explicit consent (9(2)(a)) and research under Art. 89(1) with a legal basis and safeguards (9(2)(j)). | Heart rate, HRV and sleep are health data. Sentra relies on explicit consent, so consent records must be kept for as long as the data they cover. |
| GDPR Art. 89(1) [1][4] | Research processing needs technical and organisational safeguards that respect minimisation. Pseudonymisation is one example. If the purpose can be met without identifying people, that route should be used. | Use pseudonymous participant IDs in archives. Prefer aggregated or de-identified data for anything kept long term. |
| GDPR Recital 156 [1][5] | Research safeguards should ensure minimisation. Controllers should first check whether anonymised data would meet the purpose. Member states may limit some data subject rights for research, with safeguards. | Before archiving, record why anonymised daily aggregates would not be enough. |
| ICO, "Principle (e): Storage limitation" [6] | Organisations should justify retention periods, set a policy with standard periods where possible, review periodically, and erase or anonymise data once it is no longer needed. Research and statistics are an exception that allows longer retention. | Write a retention schedule per data class, with a review date (for example, at project close) and a defined action at expiry (delete or anonymise). |

## 2. Lebanon: Law No. 81 of 10 October 2018 (Electronic Transactions and Personal Data)

| Source | What it says | How it applies to Sentra |
|---|---|---|
| DLA Piper, *Data Protection Laws of the World: Lebanon*, last reviewed 2022 [7] | The law took effect in 2019; its personal data rules are in Part V. Data must be collected for specific, explicit purposes and not exceed them. Health and genetic data need a licence from the Ministry of Economy and Trade, under a decision of the Minister of Public Health. Data subjects have rights to access and correct their data. Processors must take appropriate security measures for the nature of the data and the risks. There is no national data protection authority. Educational institutions are among the exemptions from the declaration requirement. | Purpose limitation supports deleting data once the indicators are produced. Whether the health-data licence or the declaration exemption covers AUB student research has not been confirmed. Ask the advisor or IRB. The security duty supports encryption and access control. |
| Council of Europe study on Lebanon and Convention 108 [8] | Per the search snippet, the study cites Art. 87 for purpose limitation and accuracy. It notes that to meet international standards, retention should not exceed what the purpose needs. | Shows the law has no explicit retention period. GDPR-style storage limitation is a reasonable benchmark. **(Full text not retrieved; article numbers unverified.)** |
| DataGuidance, Lebanon jurisdiction page [9] | Per search snippets, the storage-limitation principle is attributed to Art. 90. The law sets no specific retention period, and implementing regulations had not been issued. | **(Unverified; paywalled.)** Sources disagree on whether the provision is Art. 87 or Art. 90. Do not cite an article number without the official Arabic text. |

There is no reliable English full text of the law. The official Arabic text (Official Gazette, 2018) was not retrieved. Any article-level citation needs checking against it.

## 3. Research-record retention norms for human-subjects studies

| Source | What it says | How it applies to Sentra |
|---|---|---|
| US Common Rule, 45 CFR 46.115(b) [10] | IRB records must be kept at least 3 years. Records for research that is conducted must be kept at least 3 years after the research is completed. | A widely used floor for consent and protocol records. Sentra is not US-funded, but AUB's own manual mirrors this rule (see the last row). |
| HIPAA Security Rule, 45 CFR 164.316(b)(2)(i) [11] | Required policy and procedure documentation must be kept 6 years from creation or from when it was last in effect, whichever is later. | **Reference only.** Sentra is not a HIPAA covered entity. This rule covers policy documents, not health data. Do not use it to justify keeping raw data for 6 years. |
| AUB HRPP / IRB Manual, Version 8 (Feb 2020), §6.8 [12] | The PI keeps the original executed consent forms. For non-FDA studies, they must be kept at least 3 years after the study is completed. | The binding local rule: consent history must be kept at least 3 years after the project closes. |
| AUB IRB Manual (2020), p. 41 [12] | Records with personal identifiers stay under lock during and after the study, until they are destroyed or moved to a secure location. For social and behavioural studies, the PI is the usual custodian, and how long records are kept depends on the nature of the study. Research data is AUB property unless an agreement says otherwise. | The policy must name a custodian (the faculty PI or advisor, not a student) and an end-of-project handover. The IRB protocol fixes the data retention period. |
| AUB IRB Manual (2020), p. 68 [12] | Investigator records must be kept at least 3 years after the research is completed. | Same 3-year floor for correspondence and protocol records. |
| AUB HRPP policies page [13] | Index of the current HRPP policies. | The manual found is dated 2020. Confirm with the IRB (irb@aub.edu.lb) that no newer version changes these periods. |

## 4. Withdrawal of consent

| Source | What it says | How it applies to Sentra |
|---|---|---|
| GDPR Art. 7(3) [1][14] | Consent can be withdrawn at any time. Withdrawal does not make earlier processing unlawful. Withdrawing must be as easy as giving consent, and people must be told about this before they consent. | Offer a self-service withdrawal option. Indicators computed before withdrawal stay valid. Log the withdrawal in consent history. |
| GDPR Art. 17(1)(b) [1][15] | When consent under Art. 6(1)(a) or 9(2)(a) is withdrawn and no other legal ground exists, the data must be erased without undue delay. | By default, on withdrawal: stop syncing, revoke the OAuth tokens, delete raw and minute-level data, and purge it from object storage and archives. Backups should age out on their normal schedule. |
| GDPR Art. 17(3)(d) [1][15] | The right to erasure does not apply to research processing under Art. 89(1) where erasure would make the research impossible or seriously impair it. | A narrow exception. Use it only if the consent form says so and the IRB approves, for example keeping de-identified aggregates already in reported results. Do not rely on it for raw data. |
| AUB IRB Manual (2020), p. 15 [12] | The consent process must explain how data will be gathered, stored, protected, and eventually destroyed or archived. | The retention schedule and the withdrawal procedure must both appear in the consent form. |

## 5. Backup and recovery

| Source | What it says | How it applies to Sentra |
|---|---|---|
| NIST SP 800-34 Rev. 1 (2010), §3.4.2 [16] | Back up data regularly. The policy should set minimum frequency and scope based on how critical the data is, and specify the storage location, naming, rotation and offsite transport. Storing backups offsite is good practice. | Document a schedule, for example daily logical dumps of Postgres and weekly Parquet snapshots, with an offsite copy separate from Supabase. |
| NIST SP 800-34 Rev. 1, §3.5.1 and Ch. 4 [16] | Plan testing should include recovering the system from backup media. Encryption works best when applied to both primary storage and offsite backup media. Keys need sound management and should be stored separately from the data. | Run a scheduled restore test into a scratch database and record the result. Encrypt backups and keep the keys apart from the backup location. |
| NIST SP 800-209 (Oct 2020) [17] | Security guidelines for storage infrastructure. Storage-specific areas include data protection, isolation, restoration assurance and encryption, with backup and replication among its subjects. | Supports access-isolated storage buckets and restoration assurance as a named control. Detailed section citations were not extracted. |
| NIST SP 800-111 (Nov 2007) [18] | Guide to storage encryption for end-user devices: full disk, volume or virtual disk, and file or folder encryption. | Applies to any backup copy on a laptop or removable drive, which should be encrypted at rest. |
| US-CERT, "Data Backup Options" (Ruggiero and Heckathorn, CMU for US-CERT, 2012) [19] | The 3-2-1 rule: keep 3 copies (1 primary and 2 backups), on 2 different media types, with 1 copy offsite. | 3-2-1 for Sentra: the Supabase primary, an encrypted dump in a separate private bucket or provider, and an encrypted offline copy held by the custodian. |
| Supabase free-tier backups | Backup features on the free tier were not verified. | **(Unverified.)** Do not assume the provider keeps backups. Plan for self-managed `pg_dump` exports. |

Backups must also respect retention. Data deleted from the primary system, for example after a withdrawal, survives in backups until they expire. The policy should state the backup lifetime, for example 30 days, so that deletions take full effect within a known window.

## 6. Re-identification risk in high-frequency wearable data

| Source | What it says | How it applies to Sentra |
|---|---|---|
| Na et al., *JAMA Netw Open* 2018;1(8):e186040 [20] | Machine learning re-identified about 95% of adults in de-identified NHANES accelerometer data when linked with demographics. The authors suggest de-identification should aggregate data across multiple individuals. Aggregating one person's data over time did not prevent re-identification. | Detailed time series are identifying even without names. This supports shorter retention for minute and second HR data than for daily aggregates. |
| Chikwetu et al., *Lancet Digit Health* 2023;5(4):e239–e247, systematic review of 72 studies [21] | 1 to 300 seconds of wearable sensor data (for example ECG) can be enough for re-identification. The authors call for rethinking how such data is shared. | Raw heart-rate series and original API payloads are the highest-risk data classes. Keep them for the shortest period and never share or export them. |
| UAMS IRB blog, "Anonymous data from wearables" [22] | An IRB-facing summary of the same review, noting re-identification from short sensor recordings. | Plain-language support for presenting this to the AUB IRB. |

Together these suggest a tiered schedule, which the team and IRB should decide:

- raw API responses and second- or minute-level series: short (only until processing is validated)
- daily summaries: the project's duration plus the agreed archive period
- consent history: at least 3 years after the project closes [12]

---

## References

1. Regulation (EU) 2016/679 (GDPR), official text, EUR-Lex. https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng (EUR-Lex returned an empty page to the fetch tool, so content was checked against the mirror in [2]–[5], [14], [15].)
2. GDPR Art. 5 (consolidated mirror). https://gdpr-info.eu/art-5-gdpr/
3. GDPR Art. 9. https://gdpr-info.eu/art-9-gdpr/
4. GDPR Art. 89. https://gdpr-info.eu/art-89-gdpr/
5. GDPR Recital 156. https://gdpr-info.eu/recitals/no-156/
6. ICO, "Principle (e): Storage limitation." https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/storage-limitation/ (Found by search; direct fetch returned 403. Contents come from search snippets.)
7. DLA Piper, Data Protection Laws of the World: Lebanon (last reviewed 2022). https://www.dlapiperdataprotection.com/?c=LB&t=law
8. Council of Europe, study on Lebanese personal data protection law and Convention 108. https://rm.coe.int/3692-1-2-study-pdp-lebanon-coe-108-/1680a1caa2 (Exists in search results; fetch returned 403. Contents unverified.)
9. DataGuidance, Lebanon jurisdiction page. https://www.dataguidance.com/jurisdiction/lebanon (Paywalled; unverified.)
10. 45 CFR 46.115, IRB records (Cornell LII). https://www.law.cornell.edu/cfr/text/45/46.115
11. 45 CFR 164.316, policies, procedures and documentation (Cornell LII). https://www.law.cornell.edu/cfr/text/45/164.316
12. AUB Human Research Protection Program, IRB Manual, revised Version 8 (February 2020). https://www.aub.edu.lb/irb/Documents/irb_manual%20-%20revised-%20Version%208%20February%202020-.pdf
13. AUB HRPP Policies and Procedures. https://www.aub.edu.lb/irb/Pages/HRPPPoliciesandProcedures.aspx
14. GDPR Art. 7. https://gdpr-info.eu/art-7-gdpr/
15. GDPR Art. 17. https://gdpr-info.eu/art-17-gdpr/
16. NIST SP 800-34 Rev. 1, Contingency Planning Guide for Federal Information Systems (May 2010, updated Nov 2010). https://csrc.nist.gov/pubs/sp/800/34/r1/upd1/final (PDF: https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-34r1.pdf)
17. NIST SP 800-209, Security Guidelines for Storage Infrastructure (Oct 2020). https://csrc.nist.gov/pubs/sp/800/209/final
18. NIST SP 800-111, Guide to Storage Encryption Technologies for End User Devices (Nov 2007). https://csrc.nist.gov/pubs/sp/800/111/final
19. Ruggiero P., Heckathorn M. A., "Data Backup Options," Carnegie Mellon University for US-CERT, 2012. https://www.cisa.gov/sites/default/files/publications/data_backup_options.pdf
20. Na L., Yang C., Lo C.-C., Zhao F., Fukuoka Y., Aswani A. "Feasibility of Reidentifying Individuals in Large National Physical Activity Data Sets From Which Protected Health Information Has Been Removed With Use of Machine Learning." JAMA Netw Open. 2018;1(8):e186040. https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2719130
21. Chikwetu L., Miao Y., Woldetensae M. K., Bell D., Goldenholz D. M., Dunn J. "Does deidentification of data from wearable devices give us a false sense of security? A systematic review." Lancet Digit Health. 2023;5(4):e239–e247. https://pmc.ncbi.nlm.nih.gov/articles/PMC10040444
22. UAMS IRB blog, "Anonymous data from wearables." https://research.uams.edu/irb/irb-blog/anonymous-data-from-wearables/
