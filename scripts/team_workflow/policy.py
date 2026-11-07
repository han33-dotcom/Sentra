"""Deterministic PR metadata and independently approved exemption policy."""
import re
from urllib.parse import urlsplit

PROJECTS = {
    "han33-dotcom/Sentra": ("Sentra", "SEN", "develop"),
    "han33-dotcom/TechScout": ("TechScout", "TECH", "main"),
}
APPROVERS = {
    "han33-dotcom/Sentra": {"han33-dotcom", "MohamadNasrallah", "mhmdaboulhoda"},
    "han33-dotcom/TechScout": {"han33-dotcom", "MohamadNasrallah", "Ahmad860187"},
}
EXEMPTIONS = {"workflow-maintenance", "release"}
MAX_TASKS = 10
WORKFLOW_FILES = {"AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", ".gitignore"}
WORKFLOW_PREFIXES = ("docs/", ".github/", "scripts/team_workflow/", "tests/team_workflow/")


def visible_text(body):
    """Ignore comments and fenced examples when reading declared metadata."""
    lines, fence = [], False
    for line in re.sub(r"<!--[\s\S]*?(?:-->|$)", "", body or "").splitlines():
        if re.match(r"^\s*(`{3,}|~{3,})", line):
            fence = not fence
        elif not fence:
            lines.append(line)
    return "\n".join(lines)


def task_issue_number(value, repo):
    """Accept only a canonical HTTPS issue URL for the configured repository."""
    try:
        url = urlsplit(value)
        match = re.fullmatch(r"/" + re.escape(repo) + r"/issues/([1-9][0-9]*)", url.path, re.I)
        if (url.scheme == "https" and url.netloc == "github.com" and match
                and not url.query and not url.fragment):
            return int(match[1])
    except (ValueError, TypeError):
        pass
    return None


def declared_tasks(body, repo):
    """Read explicit implementation links, never incidental issue references.

    Additional Task URL lines extend the existing single-task format. Reject
    the entire declaration on error so a bad secondary link cannot be ignored.
    """
    fields = re.findall(r"^(Additional )?Task URL:[ \t]*([^\r\n]*)$", visible_text(body), flags=re.M)
    primary = [value for extra, value in fields if not extra]
    additional = [value for extra, value in fields if extra]
    if len(primary) > 1 or (additional and not primary):
        raise ValueError("Declare exactly one primary Task URL before adding implementation tasks.")
    if additional and repo != "han33-dotcom/Sentra":
        raise ValueError("Additional implementation tasks are supported only in Sentra.")
    urls = primary + additional
    limit = MAX_TASKS if repo == "han33-dotcom/Sentra" else 1
    numbers = [task_issue_number(url.strip(), repo) for url in urls]
    if len(numbers) > limit or any(n is None for n in numbers):
        raise ValueError(f"Declare at most {limit} implementation tasks, each a canonical HTTPS GitHub issue link in this repository.")
    if len(set(numbers)) != len(numbers):
        raise ValueError("Each implementation task must be declared exactly once.")
    return numbers


def task_title_prefix(repo, numbers):
    prefix = PROJECTS[repo][1]
    return "[" + ", ".join(f"{prefix}-{number}" for number in numbers) + "]"


def verified_task(client, repo, number):
    issue = client.issue(number)
    if (issue.get("number") != number or "pull_request" in issue
            or task_issue_number(issue.get("html_url", ""), repo) != number):
        raise ValueError("Task identity could not be verified in the configured repository.")
    return issue


def validate_pr_metadata(body: str, labels: set[str], repo: str, base: str, title: str = "") -> list[str]:
    """Labels must first pass approved_exemptions; this function does no network IO."""
    if repo not in PROJECTS:
        return ["Unsupported repository."]
    project, prefix, integration = PROJECTS[repo]
    text, errors = visible_text(body), []
    if base != integration and not (repo == "han33-dotcom/Sentra" and base == "main" and "release" in labels):
        errors.append("PR target does not match the project integration/release flow.")
    if "release" in labels and not (repo == "han33-dotcom/Sentra" and base == "main"):
        errors.append("Release exemption applies only to Sentra releases into main.")
    declared = re.findall(r"^Project:\s*(.*?)\s*$", text, flags=re.M)
    if declared != [project]:
        errors.append("Declare exactly one matching Project line.")
    ids = re.findall(r"^Task ID:\s*(.*?)\s*$", text, flags=re.M)
    if len(ids) > 1 or (ids and not re.fullmatch(re.escape(prefix) + r"-\d+", ids[0])):
        errors.append("Task ID must use the project's prefix and numeric ID.")
    exempt = bool(labels & EXEMPTIONS)
    try:
        numbers = declared_tasks(body, repo)
    except ValueError as error:
        errors.append(str(error))
        numbers = []
    if not numbers and not exempt:
        errors.append("Provide a Task URL or an independently approved scoped exemption.")
    if len(ids) == 1 and numbers and ids[0] != f"{prefix}-{numbers[0]}":
        errors.append("Task ID must match the first linked GitHub issue number.")
    if numbers and repo == "han33-dotcom/Sentra":
        expected = task_title_prefix(repo, numbers) + " "
        if not title.startswith(expected) or not title[len(expected):].strip():
            errors.append("Start the PR title with " + expected.strip() + " followed by a description; use every Task URL in declaration order.")
    if re.search(r"\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\b[\s:*_]+(?:#[1-9][0-9]*|[\w.-]+/[\w.-]+#[1-9][0-9]*|https://github\.com/[\w.-]+/[\w.-]+/issues/[1-9][0-9]*)", text, re.I):
        errors.append("Use Related to instead of automatic issue-closing keywords; human acceptance controls Done.")
    sections = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading[1]
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    for heading in ["What & why", "How tested", "Risks / limitations"]:
        value = "\n".join(sections.get(heading, [])).strip()
        if not value or value.lower() in {"tbd", "todo", "...", "fill in", "n/a"}:
            errors.append("Complete the " + heading + " section.")
    return errors


def approved_exemptions(pr, filenames, timeline, repo):
    """Require the latest label application by another configured human teammate."""
    errors, approved = [], set()
    active = {item["name"] for item in pr.get("labels", [])} & EXEMPTIONS
    for label in active:
        applications = [event for event in timeline
                        if event.get("event") in {"labeled", "unlabeled"}
                        and event.get("label", {}).get("name") == label]
        latest = applications[-1] if applications else {}
        actor = latest.get("actor", {}).get("login")
        if (latest.get("event") != "labeled" or actor not in APPROVERS.get(repo, set())
                or actor == pr["user"]["login"]):
            errors.append("Exemption requires a different configured teammate to apply its label.")
            continue
        if label == "workflow-maintenance":
            if not filenames or not all(
                path in WORKFLOW_FILES or path.startswith(WORKFLOW_PREFIXES)
                for path in filenames
            ):
                errors.append("Workflow exemption cannot cover application files or an empty diff.")
                continue
        if label == "release":
            if not (
                repo == "han33-dotcom/Sentra" and pr["base"]["ref"] == "main"
                and pr["head"]["ref"] == "develop"
                and pr["head"].get("repo", {}).get("full_name") == repo
            ):
                errors.append("Release exemption requires same-repository develop to main.")
                continue
        approved.add(label)
    return approved, errors
