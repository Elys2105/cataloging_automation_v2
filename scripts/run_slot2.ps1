$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment not found: $Python"
}

$env:CATALOGING_SLOT = "2"
$env:PYTHONPATH = Join-Path $Root "src"
$env:PYTHONNOUSERSITE = "1"
Set-Location -LiteralPath $Root
& $Python (Join-Path $Root "run_app.py")
exit $LASTEXITCODE
