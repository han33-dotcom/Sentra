# Reports

Task: [#42](https://github.com/han33-dotcom/Sentra/issues/42). The **Reports** page in the
private viewer produces a selected-period report for authorized colleagues. It is previewed on
the page and downloaded as a Markdown (`.md`) or PDF file. Everything in it is wellness
information compared with each person's own pattern, not a medical assessment.

## Formats

Both files are rendered from the same list of report sections (`sentra.reports.blocks`), so the
PDF never carries anything the Markdown does not. The PDF is A4 with ReportLab's standard fonts
([ReportLab](https://pypi.org/project/reportlab/) 5.0.1, BSD license). It is pure Python, and
its only dependencies (Pillow, charset-normalizer) were already in the hosted viewer's pinned
requirements. Its pages are left uncompressed and the output is reproducible, so the privacy
matrix can read the downloaded PDF's text.

## What a report contains

A report reuses the calculators behind the other pages, so it follows the same rules:

| Section | Source | Who appears |
| --- | --- | --- |
| Header | Organization, the role of the person who prepared it, period, generation time, board build time | — |
| Participation | [Organization overview](organization-overview.md) counts: enrolled, connected, recently contributing, assessable | Counts only; organization users see small activity counts as `<5` |
| Group summary | The overview's per-device group medians for the period | Each statistic needs at least 5 eligible contributors. Organization users see device labels only for publishable statistics |
| Group trends | [Trends](trends.md) group view, summarized per measure and device: days shown, lowest and highest daily median, most contributors on a day | Organization users: only devices that reach 5 on some day, no hidden-day counts |
| Individuals | Trends one-person summary per measure, plus the [observations](observations.md) for the latest published day | Only people the user may see individually **and** selected on the page |
| Follow-ups | [Follow-ups](follow-ups.md) counted by status (open, ongoing, resolved) | Counts only. Note text never enters a report |
| Limitations | Fixed list: wellness wording, provisional rules, gaps, the 5-person rule, recall and sharing | — |

Periods are the Trends periods: the last 7, 14 or 28 published days. For organization users the
group period ends on the latest day with a statistic that can be shown, so a suppressed reading
never moves it. Each individual section ends on that person's own latest published day.

## Access

- The report is rebuilt from current access and consent on every page load. Withdrawal or a
  closed membership removes that person from new organization and team reports, including both
  downloads, even if the published board still contains their rows. A change to group-only sharing
  also removes the individual section and participant follow-ups from new organization reports.
- The builder (`sentra.reports.build`) re-checks every input against the access decision, so a
  caller passing too much cannot widen a report. The [privacy matrix](privacy-checks.md) renders
  Reports with a reader that returns everyone, selects every offered person, and checks the page,
  the Markdown file and the PDF's drawn text each on its own.
- Organization users never see the board's own "data through" date, because it covers every
  organization. They see only the dates within their scope.
- Team operators get a report across all organizations, with exact participation and hidden-day
  counts. The report's data-through date comes from the eligible participants in that copy.

## Demonstration copy

The join page records whether a participant allows their pseudonymous data in internal project
demonstrations (`org.consents.demonstration`). A **demonstration copy** uses only participants
whose consent in force says so, including for the team report's data-through date. Group figures
still need 5 such participants each. The file is marked as a demonstration copy and is not for
public material ([participation permissions](participation-permissions.md)).

The demonstration copy uses only people who agreed, for group figures too. This is the cautious
reading of the consent and is open to the team's review.

## Sharing and retention

- Downloads go through the viewer's in-session download; there is no server link.
- A report reflects the permissions in force when it was generated. Later changes apply to new
  reports only, and a copy already shared cannot be recalled.
- Recipients delete downloaded copies within 30 days ([retention policy](retention-policy.md)).
- The viewer's database access is read-only, so no record is kept of who prepared or downloaded a
  report.

## Limitations

- The PDF uses standard fonts (Western European characters), which covers all report text today.
- Follow-up counts cover the latest 50 follow-ups the user may read, open and ongoing first.
- No department comparisons (no departments in the schema), and no reports through the read
  API, whose key has no organization scope.
- Pilot participants without a consent record are never in a demonstration copy.
  With today's participants every real group figure is hidden.
- Data is only as current as the daily board refresh.
