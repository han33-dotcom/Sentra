# Data and security rules

This project handles personal health data from real people (team members and, later, pilot workers).

- **Git holds code only.** Health data (`data/`, `*.db`, `*.parquet`, exports), credentials (`secrets/`, tokens,
  OAuth client files, `.env`) and generated reports never enter the repository. Enforced by `.gitignore`,
  `scripts/check_no_data.py` (pre-commit + CI) and a gitleaks scan of the full history on every push.
- **The repository stays private.** Self-hosted runners are only ever attached to this private repo.
- **Pseudonyms outside the database.** The API and processed outputs use `subject_id` (`s_xxxxxxxx`); labels and
  emails stay in the `accounts` table and are never returned.
- **API access** needs `X-API-Key`; the WHOOP webhook is verified with the HMAC signature and a 15-minute window.
- **Local-first.** Data stays on the team's own machine / server (GCC data-residency requirement).

If a secret is ever committed: rotate it first (Google Cloud console / WHOOP developer dashboard), then remove it
from history. Report problems to the repo owner, not in a public issue.
