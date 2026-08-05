param(
    [string]$RepoUrl = "https://gitee.com/Lee157/finance-skills.git",
    [string]$Branch = "main",
    [switch]$NoRestart,
    [switch]$ValidateOnly,
    [switch]$BaselineOnly
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Git = (Get-Command git -ErrorAction Stop).Source
$Checkout = Join-Path $ProjectRoot ".skill-sync\finance-skills"
$SourceSkills = Join-Path $Checkout "skills"
$PlatformSkills = Join-Path $ProjectRoot "skills"
$BackupRoot = Join-Path $ProjectRoot "data\backups\skill-sync"
$LockPath = Join-Path $ProjectRoot "data\skill-sync.lock"
$StatePath = Join-Path $ProjectRoot "data\skill-sync-state.json"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python virtual environment not found: $Python"
}
if (-not (Test-Path -LiteralPath $PlatformSkills)) {
    throw "Platform Skill directory not found: $PlatformSkills"
}

$lock = $null
try {
    New-Item -ItemType Directory -Force -Path (Split-Path $LockPath), (Split-Path $Checkout), $BackupRoot | Out-Null
    $lock = [System.IO.File]::Open($LockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)

    if (-not (Test-Path -LiteralPath (Join-Path $Checkout ".git"))) {
        if (Test-Path -LiteralPath $Checkout) {
            Remove-Item -LiteralPath $Checkout -Recurse -Force
        }
        & $Git clone --depth 1 --branch $Branch $RepoUrl $Checkout
        if ($LASTEXITCODE -ne 0) { throw "Gitee clone failed, exit code $LASTEXITCODE" }
    }
    else {
        & $Git -C $Checkout fetch --prune origin $Branch
        if ($LASTEXITCODE -ne 0) { throw "Gitee fetch failed, exit code $LASTEXITCODE" }
        & $Git -C $Checkout checkout --force $Branch
        if ($LASTEXITCODE -ne 0) { throw "Branch checkout failed, exit code $LASTEXITCODE" }
        & $Git -C $Checkout reset --hard "origin/$Branch"
        if ($LASTEXITCODE -ne 0) { throw "Checkout reset failed, exit code $LASTEXITCODE" }
    }

    if (-not (Test-Path -LiteralPath $SourceSkills)) {
        throw "Gitee repository has no skills directory: $SourceSkills"
    }
    $required = @("ar-hexiao-daily", "receivables-merge")
    foreach ($skill in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $SourceSkills $skill))) {
            throw "Required Skill missing from Gitee: $skill"
        }
    }

    $sha = (& $Git -C $Checkout rev-parse HEAD).Trim()
    if (-not $sha) { throw "Unable to read Gitee commit SHA" }
    if (Test-Path -LiteralPath $StatePath) {
        $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        if ($state.sha -eq $sha) {
            Write-Host "No new Gitee commit ($($sha.Substring(0, 8))); skipping sync."
            exit 0
        }
    }

    $wasRunning = Test-Path -LiteralPath (Join-Path $ProjectRoot "data\runtime.json")
    if ($wasRunning -and $NoRestart) {
        throw "Cannot use -NoRestart while platform is running."
    }
    $runtime = $null
    if ($wasRunning) {
        try { $runtime = Get-Content (Join-Path $ProjectRoot "data\runtime.json") -Raw | ConvertFrom-Json } catch { $runtime = $null }
    }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = Join-Path $BackupRoot $stamp
    $stageRoot = Join-Path $ProjectRoot ".skill-sync\staging\$sha"
    $stageSkills = Join-Path $stageRoot "skills"
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
    Copy-Item -LiteralPath $PlatformSkills -Destination $stageSkills -Recurse
    & $Python (Join-Path $PSScriptRoot "sync_finance_skills.py") `
        --source $SourceSkills --target $stageSkills
    if ($LASTEXITCODE -ne 0) { throw "Staging sync failed, exit code $LASTEXITCODE" }
    if ($ValidateOnly) {
        Write-Host "Staging validation passed for Gitee $($sha.Substring(0, 8)); platform unchanged."
        if ($BaselineOnly) {
            @{
                sha = $sha
                short_sha = $sha.Substring(0, 8)
                repository = $RepoUrl
                branch = $Branch
                synced_at = (Get-Date).ToString("o")
                baseline_only = $true
            } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
            Write-Host "Recorded remote baseline; local unpublished Skills will not be downgraded."
        }
        exit 0
    }

    Copy-Item -LiteralPath $PlatformSkills -Destination $backup -Recurse

    if ($wasRunning -and -not $NoRestart) {
        & (Join-Path $PSScriptRoot "stop.ps1")
        if ($LASTEXITCODE -ne 0) { throw "Platform stop failed; Skill sync was not applied." }
    }

    try {
        Remove-Item -LiteralPath $PlatformSkills -Recurse -Force
        Move-Item -LiteralPath $stageSkills -Destination $PlatformSkills
    }
    catch {
        Remove-Item -LiteralPath $PlatformSkills -Recurse -Force
        Copy-Item -LiteralPath $backup -Destination $PlatformSkills -Recurse
        if ($wasRunning -and -not $NoRestart) {
            & (Join-Path $PSScriptRoot "start.ps1") -NoBrowser
        }
        throw
    }

    Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue

    if ($wasRunning -and -not $NoRestart) {
        $startArgs = @{ NoBrowser = $true }
        if ($runtime -and $runtime.port) { $startArgs.Port = [int]$runtime.port }
        if ($runtime -and $runtime.host) { $startArgs.HostAddress = [string]$runtime.host }
        & (Join-Path $PSScriptRoot "start.ps1") @startArgs
        if ($LASTEXITCODE -ne 0) { throw "Platform restart failed; check data\logs." }
        try {
            $healthPort = 8000
            if ($startArgs.ContainsKey("Port")) { $healthPort = [int]$startArgs.Port }
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$healthPort/api/health" -TimeoutSec 10
            if ($health.status -ne "ok") { throw "Health check returned a non-ok status." }
        } catch {
            throw "Platform health check failed: $($_.Exception.Message)"
        }
    }

    @{
        sha = $sha
        short_sha = $sha.Substring(0, 8)
        repository = $RepoUrl
        branch = $Branch
        synced_at = (Get-Date).ToString("o")
        backup = $backup
    } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
    Write-Host "Synced Gitee $($sha.Substring(0, 8)); backup saved at $backup"
}
finally {
    if ($lock) { $lock.Dispose() }
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}
