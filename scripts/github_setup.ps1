# One-time GitHub setup for the Sentra FYP monorepo. Run from the FYP folder in PowerShell:
#
#   powershell -ExecutionPolicy Bypass -File scripts\github_setup.ps1 -Org sentra-fyp -Teammates hasan-gh,abolhoda-gh
#
# Before running:
#   1. Create the organization in the browser (free plan): https://github.com/account/organizations/new?plan=free
#   2. Install the GitHub CLI:  winget install GitHub.cli    then:  gh auth login   (scopes: repo, workflow, admin:org)
# Safe to re-run: every step skips or overwrites what already exists.

param(
    [Parameter(Mandatory = $true)][string]$Org,
    [string]$Repo = "sentra",
    [string[]]$Teammates = @(),
    [ValidateSet("private", "public")][string]$Visibility = "private"
)
$ErrorActionPreference = "Continue"   # gh writes to stderr on "not found"; we check $LASTEXITCODE instead
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$full = "$Org/$Repo"

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Try-Gh([scriptblock]$cmd, [string]$what) {
    & $cmd 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host "   (skipped: $what - needs a paid plan or admin rights)" -ForegroundColor Yellow; $global:LASTEXITCODE = 0 }
    else { Write-Host "   ok: $what" }
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "Install the GitHub CLI first: winget install GitHub.cli" }
gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Run: gh auth login" }

Step "Data guard (nothing personal gets pushed)"
python scripts\check_no_data.py
if ($LASTEXITCODE -ne 0) { throw "Fix the blocked files above before pushing." }

Step "Repository $full ($Visibility)"
gh repo view $full 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    gh repo create $full "--$Visibility" --description "Sentra: consumer wearables -> fitness-for-shift signals for HSE teams (AUB FYP)" --disable-wiki
}
$remote = git remote get-url origin 2>$null
if (-not $remote) { git remote add origin "https://github.com/$full.git" }
git push -u origin main
if ($LASTEXITCODE -ne 0) { throw "push failed" }

Step "Labels"
Get-Content .github\labels.yml | Where-Object { $_ -match '^\- \[(.+?), ([0-9a-f]{6}), (.+)\]$' } | ForEach-Object {
    gh label create $Matches[1] --color $Matches[2] --description $Matches[3] --repo $full --force | Out-Null
}
Write-Host "   ok"

Step "Repository settings"
gh repo edit $full --enable-squash-merge --enable-merge-commit=false --enable-rebase-merge=false `
    --delete-branch-on-merge --enable-auto-merge | Out-Null
Try-Gh { gh api -X PUT "repos/$full/vulnerability-alerts" } "Dependabot alerts"
Try-Gh { gh api -X PUT "repos/$full/automated-security-fixes" } "Dependabot security updates"
gh variable set DEPLOY_ENABLED --body "false" --repo $full | Out-Null   # flip to true once the runner is installed
Write-Host "   ok: squash merges only, branches deleted after merge, DEPLOY_ENABLED=false"

Step "Protect main (PR + review + green CI)"
$protection = @{
    required_status_checks        = @{ strict = $true; contexts = @(
            "Guard (no data, no secrets)",
            "Lint & test (ubuntu-latest, py3.12)",
            "Lint & test (windows-latest, py3.12)",
            "Docker image") }
    enforce_admins                = $false
    required_pull_request_reviews = @{ required_approving_review_count = 1; dismiss_stale_reviews = $true }
    restrictions                  = $null
    allow_force_pushes            = $false
    allow_deletions               = $false
    required_linear_history       = $true
} | ConvertTo-Json -Depth 5
$tmp = New-TemporaryFile
[IO.File]::WriteAllText($tmp.FullName, $protection)   # no BOM
Try-Gh { gh api -X PUT "repos/$full/branches/main/protection" --input $tmp.FullName } "branch protection on main"
Remove-Item $tmp

Step "GitHub Pages for website/ (deployed by .github/workflows/website.yml)"
Try-Gh { gh api -X POST "repos/$full/pages" -f build_type=workflow } "Pages (source: GitHub Actions)"

Step "Team"
if ($Teammates.Count -gt 0) {
    gh api "orgs/$Org/teams/core" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { gh api -X POST "orgs/$Org/teams" -f name=core -f privacy=closed | Out-Null }
    gh api -X PUT "orgs/$Org/teams/core/repos/$full" -f permission=maintain | Out-Null
    foreach ($u in $Teammates) {
        Try-Gh { gh api -X PUT "orgs/$Org/teams/core/memberships/$u" -f role=member } "invite $u to team core"
    }
} else { Write-Host "   no -Teammates given; invite them later with -Teammates user1,user2" }

Write-Host "`nDone: https://github.com/$full" -ForegroundColor Green
Write-Host "Next: docs\DEPLOYMENT.md (self-hosted runner -> automatic backend deploys)."
