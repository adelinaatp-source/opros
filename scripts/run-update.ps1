[CmdletBinding()]
param(
    [string]$SourcePath = '\\PC-BA2\KB-ARM-survey'
)

$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OutDir = Join-Path $ProjectRoot 'out'
$LogPath = Join-Path $OutDir 'scheduled-update.log'

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

function Write-UpdateLog {
    param([string]$Message)
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $LogPath -Value "[$stamp] $Message" -Encoding UTF8
}

function Invoke-Checked {
    param(
        [string]$Name,
        [scriptblock]$Command
    )
    Write-UpdateLog "START $Name"
    $ErrorActionPreference = 'Continue'
    $commandOutput = & $Command 2>&1
    $commandExitCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $commandOutput | ForEach-Object { Add-Content -LiteralPath $LogPath -Value $_ -Encoding UTF8 }
    if ($commandExitCode -ne 0) {
        throw "$Name failed with exit code $commandExitCode"
    }
    Write-UpdateLog "OK $Name"
}

try {
    Write-UpdateLog 'Daily update started'
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Container)) {
        throw "Source is unavailable: $SourcePath"
    }

    Set-Location -LiteralPath $ProjectRoot
    $pending = git status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to inspect Git status'
    }
    if ($pending) {
        throw 'Tracked working tree changes are present'
    }

    Invoke-Checked 'git pull --ff-only' { git pull --ff-only origin main }
    Invoke-Checked 'update index.html' { python scripts/update_site.py --source $SourcePath }
    Invoke-Checked 'focused tests' { python -m unittest discover -s tests -p 'test_*.py' }
    Invoke-Checked 'HTML/JavaScript and filters' { node scripts/validate_site.js }
    Invoke-Checked 'git diff --check' { git diff --check }

    git diff --quiet -- index.html
    if ($LASTEXITCODE -eq 0) {
        Write-UpdateLog 'No new data; commit not created'
        exit 0
    }
    if ($LASTEXITCODE -ne 1) {
        throw "git diff failed with exit code $LASTEXITCODE"
    }

    Invoke-Checked 'git add index.html' { git add -- index.html }
    $message = 'Auto-update surveys: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm')
    Invoke-Checked 'git commit' { git commit -m $message }
    Write-UpdateLog 'Local auto-commit created; push is disabled'
}
catch {
    Write-UpdateLog ("ERROR " + $_.Exception.Message)
    exit 1
}
