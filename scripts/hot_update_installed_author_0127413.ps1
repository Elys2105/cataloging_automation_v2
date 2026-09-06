param(
    [string]$Root = "D:\DACN\JOB2\cataloging_automation_v2",
    [string]$InstallDir = "$env:ProgramFiles\Automation bien muc tai lieu",
    [switch]$UseExistingBuild
)

$ErrorActionPreference = "Stop"
$ExpectedVersion = "0.1.27.4.13"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Backup = Join-Path $Root ("runtime\hotfix-installed-backups\author_robust_0127413_" + $stamp)
$Results = Join-Path $Root ("runtime\hotfix-results\author_robust_0127413_" + $stamp)

function Require-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object -TypeName System.Security.Principal.WindowsPrincipal -ArgumentList $identity
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "HOT_UPDATE_REQUIRES_ADMIN: Open PowerShell as Administrator and rerun."
    }
}

function Restore-InstalledBackup {
    if (-not (Test-Path -LiteralPath $Backup)) { return }

    $map = @{
        "AutomationBienMuc.exe" = (Join-Path $InstallDir "AutomationBienMuc.exe")
        "_internal\pyproject.toml" = (Join-Path $InstallDir "_internal\pyproject.toml")
        "_internal\config\default.yaml" = (Join-Path $InstallDir "_internal\config\default.yaml")
    }

    foreach ($rel in $map.Keys) {
        $src = Join-Path $Backup $rel
        $dst = $map[$rel]
        if (Test-Path -LiteralPath $src -PathType Leaf) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
    }
}

function Invoke-SelfCheck {
    param(
        [string]$Exe,
        [int]$Slot,
        [string]$Report
    )

    if (Test-Path -LiteralPath $Report) {
        Remove-Item -LiteralPath $Report -Force
    }

    $p = Start-Process `
        -FilePath $Exe `
        -ArgumentList @("--slot", "$Slot", "--self-check", "--report", $Report) `
        -Wait `
        -PassThru

    if ($p.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Report -PathType Leaf)) {
        throw "Self-check failed for Slot $Slot (exit $($p.ExitCode))"
    }

    $payload = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
    if (-not $payload.ok) {
        $payload | ConvertTo-Json -Depth 8 | Write-Host
        throw "Self-check reported blockers for Slot $Slot"
    }
    if ([string]$payload.version -ne $ExpectedVersion) {
        throw "Version mismatch for Slot ${Slot}: $($payload.version)"
    }

    return $payload
}

Require-Administrator

Write-Host "[HOT UPDATE] 01 pre-flight" -ForegroundColor Cyan

$InstalledExe = Join-Path $InstallDir "AutomationBienMuc.exe"
if (-not (Test-Path -LiteralPath $InstalledExe -PathType Leaf)) {
    throw "Installed executable not found: $InstalledExe"
}

$running = @(Get-Process -Name "AutomationBienMuc" -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
    $running | Select-Object Id,ProcessName,StartTime | Format-Table | Out-String | Write-Host
    throw "Close Slot 1 and Slot 2 completely before hot update."
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Missing project Python: $Python"
}

$projectVersion = (& $Python (Join-Path $Root "scripts\read_project_version.py") $Root).Trim()
if ($projectVersion -ne $ExpectedVersion) {
    throw "Source must be $ExpectedVersion before installed hot update; found: $projectVersion"
}

$Dist = Join-Path $Root "dist\AutomationBienMuc"
$NewExe = Join-Path $Dist "AutomationBienMuc.exe"
$NewPyProject = Join-Path $Dist "_internal\pyproject.toml"
$NewDefault = Join-Path $Dist "_internal\config\default.yaml"

if (-not $UseExistingBuild) {
    Write-Host "[HOT UPDATE] 02 rebuild packaged app (no installer/uninstaller)" -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $Root "scripts\build_windows.ps1") `
        -SkipInstaller
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller hotfix build failed"
    }
}
else {
    Write-Host "[HOT UPDATE] 02 reuse existing build after validating version" -ForegroundColor Cyan
}

foreach ($path in @($NewExe, $NewPyProject, $NewDefault)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Hotfix build output missing: $path"
    }
}

New-Item -ItemType Directory -Force -Path $Results | Out-Null

# Validate the newly built dist before touching Program Files.
$distReport = Join-Path $Results "dist-self-check-slot1.json"
Invoke-SelfCheck -Exe $NewExe -Slot 1 -Report $distReport | Out-Null

Write-Host "[HOT UPDATE] 03 backup installed binaries" -ForegroundColor Cyan
$installedMap = @{
    "AutomationBienMuc.exe" = $InstalledExe
    "_internal\pyproject.toml" = (Join-Path $InstallDir "_internal\pyproject.toml")
    "_internal\config\default.yaml" = (Join-Path $InstallDir "_internal\config\default.yaml")
}

foreach ($rel in $installedMap.Keys) {
    $src = $installedMap[$rel]
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) {
        throw "Installed hot-update target missing: $src"
    }

    $dst = Join-Path $Backup $rel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Force
}

try {
    Write-Host "[HOT UPDATE] 04 deploy in place" -ForegroundColor Cyan
    Copy-Item -LiteralPath $NewExe -Destination $InstalledExe -Force
    Copy-Item -LiteralPath $NewPyProject `
        -Destination (Join-Path $InstallDir "_internal\pyproject.toml") -Force
    Copy-Item -LiteralPath $NewDefault `
        -Destination (Join-Path $InstallDir "_internal\config\default.yaml") -Force

    $installedHash = (Get-FileHash -LiteralPath $InstalledExe -Algorithm SHA256).Hash
    $distHash = (Get-FileHash -LiteralPath $NewExe -Algorithm SHA256).Hash
    if ($installedHash -ne $distHash) {
        throw "Installed EXE hash does not match newly built EXE"
    }

    Write-Host "[HOT UPDATE] 05 installed self-check Slot 1/2" -ForegroundColor Cyan
    foreach ($slot in 1,2) {
        $report = Join-Path $Results ("installed-self-check-slot{0}.json" -f $slot)
        $payload = Invoke-SelfCheck -Exe $InstalledExe -Slot $slot -Report $report
        Write-Host ("Slot {0}: OK, version {1}" -f $slot, $payload.version) -ForegroundColor Green
    }

    @(
        "HOT_UPDATE_SUCCESS",
        "VERSION=$ExpectedVersion",
        "INSTALL_DIR=$InstallDir",
        "INSTALLED_EXE_SHA256=$installedHash",
        "BACKUP=$Backup",
        "RESULTS=$Results",
        "USER_DATA_UNTOUCHED=$env:LOCALAPPDATA\KhoLuuTruAutomation"
    ) | Set-Content -LiteralPath (Join-Path $Results "SUMMARY.txt") -Encoding UTF8

    Write-Host ""
    Write-Host "HOT_UPDATE_SUCCESS" -ForegroundColor Green
    Write-Host "VERSION : $ExpectedVersion"
    Write-Host "INSTALL : $InstallDir"
    Write-Host "BACKUP  : $Backup"
    Write-Host "RESULTS : $Results"
    Write-Host "No Setup.exe or uninstaller was executed."
    Write-Host "LocalAppData database/profile/job data were not replaced."
}
catch {
    Write-Host ""
    Write-Host "HOT UPDATE FAILED - RESTORING INSTALLED BINARIES..." -ForegroundColor Yellow
    Restore-InstalledBackup
    Write-Host "INSTALLED_ROLLBACK_COMPLETE" -ForegroundColor Yellow
    throw
}
