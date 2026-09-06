param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [switch]$FailOnFullRuff,
    [switch]$FailOnPyright
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath $Root).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Python environment not found: $Python" }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $Root ("runtime\release-hardening\" + $stamp)
New-Item -ItemType Directory -Force -Path $out | Out-Null

$env:PYTHONPATH = Join-Path $Root "src"
$env:PYTHONNOUSERSITE = "1"

function Run-Native {
    param(
        [string]$Name,
        [string]$Exe,
        [string[]]$Arguments,
        [bool]$Blocking = $true
    )
    $log = Join-Path $out ($Name + ".txt")
    Push-Location -LiteralPath $Root
    try {
        $old = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $Exe @Arguments *> $log
        $code = $LASTEXITCODE
        $ErrorActionPreference = $old
    }
    finally {
        Pop-Location
    }
    Add-Content -LiteralPath $log -Value ("EXIT_CODE=" + $code)
    if ($Blocking -and $code -ne 0) {
        throw ($Name + " failed with exit code " + $code + ". See " + $log)
    }
    return $code
}

Write-Host "[C] 01 import path"
$ExpectedSource = Join-Path $Root "src"
Run-Native "01_import_path" $Python @("-c", "import pathlib,cataloging_tool; p=pathlib.Path(cataloging_tool.__file__).resolve(); expected=pathlib.Path(r'$ExpectedSource').resolve(); print(p); print(expected); assert expected in p.parents") | Out-Null

Write-Host "[C] 02 version sync"
Run-Native "02_version" $Python @("scripts\read_project_version.py", $Root) | Out-Null
Run-Native "02_version_sync" $Python @("-c", "import pathlib,tomllib,yaml; r=pathlib.Path(r'$Root'); a=tomllib.loads((r/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']; b=yaml.safe_load((r/'config/default.yaml').read_text(encoding='utf-8'))['application']['version']; print('pyproject='+a); print('default='+b); assert a==b") | Out-Null

Write-Host "[C] 03 pip check"
Run-Native "03_pip_check" $Python @("-m", "pip", "check") | Out-Null

Write-Host "[C] 04 compileall"
Run-Native "04_compileall" $Python @("-m", "compileall", "-q", "src", "tests", "scripts") | Out-Null

Write-Host "[C] 05 pytest"
Run-Native "05_pytest" $Python @("-m", "pytest", "-q", (Join-Path $Root "tests")) | Out-Null

Write-Host "[C] 06 dependency health"
$depCode = Run-Native "06_dependency_health" $Python @("scripts\check_dependency_conflicts.py", "--json") $false

Write-Host "[C] 07 Ruff critical"
Run-Native "07_ruff_critical" $Python @("-m", "ruff", "check", "src", "tests", "scripts", "--select", "E9,F63,F7,F82") | Out-Null

Write-Host "[C] 08 Ruff full report"
$ruffCode = Run-Native "08_ruff_full" $Python @("-m", "ruff", "check", "src", "tests", "scripts") $false
if ($FailOnFullRuff -and $ruffCode -ne 0) { throw "Full Ruff report contains errors" }

Write-Host "[C] 09 Pyright full report"
$pyrightCode = Run-Native "09_pyright_full" $Python @("-m", "pyright") $false
if ($FailOnPyright -and $pyrightCode -ne 0) { throw "Pyright report contains errors" }

$summary = @(
    "RELEASE_HARDENING_COMPLETE"
    "ROOT=$Root"
    "RESULTS=$out"
    "DEPENDENCY_EXIT=$depCode"
    "RUFF_FULL_EXIT=$ruffCode"
    "PYRIGHT_EXIT=$pyrightCode"
    "STATIC_REPORTS_ARE_ADVISORY_UNLESS -FailOnFullRuff/-FailOnPyright IS USED"
)
$summary | Set-Content -LiteralPath (Join-Path $out "00_SUMMARY.txt") -Encoding UTF8
$summary | ForEach-Object { Write-Host $_ }

if ($depCode -ne 0) {
    Write-Host "NOT_READY_FOR_RELEASE: dependency blocker remains" -ForegroundColor Yellow
    exit 2
}

if ($ruffCode -ne 0 -or $pyrightCode -ne 0) {
    Write-Host "RELEASE_HARDENING_PASS_WITH_STATIC_ADVISORIES" -ForegroundColor Yellow
    exit 0
}

Write-Host "RELEASE_HARDENING_PASS" -ForegroundColor Green
exit 0
