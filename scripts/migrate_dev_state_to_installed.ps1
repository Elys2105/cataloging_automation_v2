param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [switch]$IncludeCaches
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $Root).Path
$DataRoot = Join-Path $env:LOCALAPPDATA "KhoLuuTruAutomation"

function Copy-StateTree {
    param(
        [string]$Source,
        [string]$Destination
    )
    if (-not (Test-Path $Source)) { return }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $exclude = @("browser-profile")
    if (-not $IncludeCaches) {
        $exclude += @("pdf", "rendered", "ocr", "downloads")
    }

    $args = @($Source, $Destination, "/E", "/COPY:DAT", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS")
    foreach ($name in $exclude) {
        $args += @("/XD", (Join-Path $Source $name))
    }
    & robocopy @args | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed for $Source -> $Destination (exit $LASTEXITCODE)"
    }
}

Copy-StateTree `
    -Source (Join-Path $Root "runtime") `
    -Destination (Join-Path $DataRoot "slot1\runtime")

Copy-StateTree `
    -Source (Join-Path $Root "runtime\slot2") `
    -Destination (Join-Path $DataRoot "slot2\runtime")

Write-Host "Development state migrated to: $DataRoot" -ForegroundColor Green
Write-Host "Legacy Chrome profiles are not moved; installed mode reuses them automatically when present."
