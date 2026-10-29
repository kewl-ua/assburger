# commit_push.ps1 - stage the curated tree, commit and push origin/master.
# Run only after an approved change:
#   powershell -ExecutionPolicy Bypass -File commit_push.ps1 -Message "what changed"
param(
    [Parameter(Mandatory = $true)]
    [string]$Message
)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
git add -A
$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host "nothing staged (already up to date)" -ForegroundColor Yellow
    exit 0
}
git commit -m $Message
git push origin HEAD
Write-Host "pushed: $Message" -ForegroundColor Green
