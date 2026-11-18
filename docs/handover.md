# Operator handover

Task: [SEN-32](https://github.com/han33-dotcom/Sentra/issues/32). Where to look for each operating
situation, in one place. Each row links the reviewed procedure, which stays the source of truth;
nothing here replaces it. See the [architecture](architecture.md) for how the parts fit together.

Collection stays paused until the team agrees the restart. No step here authorizes restarting it,
and nothing here deletes data.

## Before you start

- **Accounts and custody:** the dedicated Sentra identity administers Google Cloud, Supabase,
  Render and Streamlit Community Cloud. Streamlit hosting management still depends on the linked
  repository owner's GitHub account. Custodian details, recovery methods and secret locations are
  in the restricted operator inventory, never in GitHub
  ([service account handoff](service-account-handoff.md)).
- **Local setup:** [collaborator setup](collaborator-setup.md), then
  [operator setup](operating-guide.md#operator-setup). Keep `.private` on the operator's machine.
  Never copy it to Streamlit or into chat, issues or screenshots.
- **Team rules:** work in GitHub issues and pull requests into `develop`; releases go
  `develop` → `main` ([team workflow](team-workflow.md)).

## By situation

| Situation | Procedure |
| --- | --- |
| Daily operation and first checks | [Operating guide: start here](operating-guide.md#start-here) |
| Run a collection manually or reconnect a provider | [Manual runs and reconnect](operating-guide.md#manual-runs-and-reconnect) |
| Restart collection (needs team agreement) | [Collection restart readiness](collection-restart-readiness.md#outstanding-restart-gates) |
| A read fails, or capacity or egress is near a ceiling | [Read failures and capacity](operating-guide.md#read-failures-and-capacity), [capacity measurements](capacity-measurements.md) |
| The wellness board did not refresh | [Wellness board](wellness-board.md) |
| Restore or check the hosted viewer | [Dashboard restoration](dashboard-restoration.md#hosted-configuration-and-recovery) |
| Enroll participants or deploy the enrollment service | [Before enrolling anyone](participation-permissions.md#before-enrolling-anyone), [prepare a deployment](self-service-enrollment.md#prepare-a-deployment) |
| Link an existing Fitbit participant to hosted sign-in | [Link an existing Fitbit participant](self-service-enrollment.md#link-an-existing-fitbit-participant) |
| A participant withdraws or changes their sharing | [Withdrawal](participation-permissions.md#withdrawal); retention after withdrawal: [retention policy](retention-policy.md#withdrawal-proposed) |
| Give an organization officer or reviewer access | [Roles](participation-permissions.md#roles); participation and authorized officer duties may coexist. Never grant a role merely to use a participant as a test identity. Use designated synthetic fixtures for acceptance. |
| Set up follow-up recording on the hosted viewer | [Follow-ups: operator setup](follow-ups.md#operator-setup-private) |
| Take and verify a backup | [Backup and recovery](operating-guide.md#backup-and-recovery), [backups](retention-policy.md#backups) |
| Rehearse a recovery into a throwaway project | [Recovery rehearsal](recovery-rehearsal.md) |
| Add and verify compact storage (phases 1–2; no deletion) | [Storage plan](storage-plan.md#phases-and-approvals) |
| Any step that would delete stored data, including removing rows after compaction | [Gates before any destructive storage step](retention-policy.md#gates-before-any-destructive-storage-step-46), [storage plan](storage-plan.md#phases-and-approvals) |
| Run the hosted access and withdrawal checks | [Privacy checks](privacy-checks.md) |
| Recover a service account or check the privacy policy link | [Service account handoff](service-account-handoff.md#recovery-and-verification) |
| Approve or change observation rules | [Observation approval](operating-guide.md#observation-approval-and-documentation), [indicator contract](indicator-contract.md) |

## Definitions

- What is stored and where: [schema](schema.md), [data dictionary](data-dictionary.md).
- What the wellness outputs mean: [processing](processing.md), [indicator contract](indicator-contract.md),
  [medical evidence](medical-evidence.md).
- Who may see what: [participation permissions](participation-permissions.md),
  [organization overview](organization-overview.md).

## Open decisions and gates

These decisions belong to the team or the medical expert. Until they are recorded,
the related steps stay closed:

- **Participation setup:** team approval was reported November 18 and the owner removed
  the advisor-review outcome from sprint scope. Participant-specific consent and public-policy
  publication still apply ([before enrolling anyone](participation-permissions.md#before-enrolling-anyone), SEN-26).
- **Collection restart** ([outstanding restart gates](collection-restart-readiness.md#outstanding-restart-gates)).
- **Live destructive-operation approval:** the interim retention policy is team agreed and
  backup/recovery verified (SEN-29/SEN-30); exact previews and owner approvals still apply.
  Post-project custody is outside this sprint ([retention policy](retention-policy.md)).
- **Medical expert sign-off on thresholds** ([indicator contract](indicator-contract.md),
  SEN-49). The dashboard owner agreed the v0 names/states/meanings on November 14;
  that agreement does not approve the thresholds.
- **Hosted verification** of the organization pages after the next release: run the
  [privacy checks](privacy-checks.md) and fill in the hosted column of the
  [evaluation table](evaluation.md).

Remaining gaps are listed in [limitations](limitations.md).
