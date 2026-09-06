$ErrorActionPreference = "Stop"

$common = Join-Path $PSScriptRoot "inno_setup_common.ps1"
if (-not (Test-Path -LiteralPath $common)) {
    throw "Missing Inno Setup helper: $common"
}
. $common

$iscc = Get-InnoSetupCompilerPath
if ($iscc) {
    Write-Host "Inno Setup found: $iscc" -ForegroundColor Green
    exit 0
}

$winget = Get-Command winget.exe -ErrorAction SilentlyContinue
if (-not $winget) {
    throw "Inno Setup 6 is missing and winget is unavailable. Install Inno Setup 6, then rerun the build."
}

Write-Host "Inno Setup compiler was not found. Repair/installing Inno Setup 6 with winget..." -ForegroundColor Yellow
& $winget.Source install `
    --id JRSoftware.InnoSetup `
    --exact `
    --silent `
    --force `
    --accept-package-agreements `
    --accept-source-agreements

$wingetExit = $LASTEXITCODE

# Some winget states (for example, package already present/no applicable upgrade)
# can return a non-zero code even though Inno Setup is installed. Always resolve
# ISCC.exe again before deciding that the operation failed.
$iscc = Get-InnoSetupCompilerPath
if ($iscc) {
    Write-Host "Inno Setup ready: $iscc" -ForegroundColor Green
    exit 0
}

if ($wingetExit -ne 0) {
    throw "winget did not make ISCC.exe available (exit $wingetExit)."
}

throw "winget completed but ISCC.exe still could not be located."
