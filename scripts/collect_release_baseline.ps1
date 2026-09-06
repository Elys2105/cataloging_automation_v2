param(
    [string]$Root = "D:\DACN\JOB2\cataloging_automation_v2"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Root)) {
    throw "Project root not found: $Root"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outRoot = Join-Path $Root "runtime\audit"
$stage = Join-Path $outRoot ("release_baseline_" + $stamp)
$zip = Join-Path $outRoot ("release_baseline_" + $stamp + ".zip")
$manifest = Join-Path $stage "RELEASE_BASELINE_MANIFEST.txt"

New-Item -ItemType Directory -Force -Path $stage | Out-Null

$excludeTop = @(
    ".venv",
    "runtime",
    "backup",
    "backups",
    "dist",
    "release",
    ".git"
)

$excludeNames = @(
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".pyright",
    "node_modules"
)

$excludeFileNames = @(
    "local.yaml",
    ".env",
    ".env.local"
)

$excludeExt = @(
    ".pyc",
    ".pyo",
    ".log",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".pdf"
)

function Is-ExcludedPath {
    param([string]$FullName)

    $rel = $FullName.Substring($Root.Length).TrimStart('\')
    $first = ($rel -split '\\')[0]
    if ($first -like "backup*" -or $first -like "*backup*") {
        return $true
    }

    foreach ($top in $excludeTop) {
        if ($rel -eq $top -or $rel.StartsWith($top + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    $parts = $rel -split '\\'
    foreach ($name in $excludeNames) {
        if ($parts -contains $name) { return $true }
    }

    $leaf = Split-Path -Leaf $FullName
    if ($excludeFileNames -contains $leaf) { return $true }

    $ext = [System.IO.Path]::GetExtension($leaf)
    if ($excludeExt -contains $ext) { return $true }

    if ($leaf -match '\.bak$' -or $leaf -match '\.backup$' -or $leaf -match 'before_fixed_') {
        return $true
    }

    return $false
}

Get-ChildItem -LiteralPath $Root -Recurse -File -Force |
    Where-Object { -not (Is-ExcludedPath $_.FullName) } |
    ForEach-Object {
        $rel = $_.FullName.Substring($Root.Length).TrimStart('\')
        $dst = Join-Path $stage $rel
        $parent = Split-Path -Parent $dst
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
    }

# Remove any sensitive file if a nested copy rule ever missed it.
Get-ChildItem -LiteralPath $stage -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -ieq "local.yaml" -or
        $_.Name -match '^\.env($|\.)' -or
        $_.Extension -in @(".sqlite", ".sqlite3", ".db", ".pdf", ".log")
    } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$python = Join-Path $Root ".venv\Scripts\python.exe"
$meta = New-Object System.Collections.Generic.List[string]
$meta.Add("CATALOGING AUTOMATION RELEASE BASELINE")
$meta.Add("Root: $Root")
$meta.Add("Created: $(Get-Date -Format o)")
$meta.Add("Excluded: .venv, runtime, backups, dist, release, .git, local.yaml, env files, databases, PDFs, logs")
$meta.Add("")

if (Test-Path $python) {
    $meta.Add("PYTHON:")
    $meta.Add((& $python --version 2>&1 | Out-String).Trim())
    $meta.Add("")
    $meta.Add("PACKAGE VERSION:")
    $versionCode = @'
import pathlib, tomllib
p = pathlib.Path("pyproject.toml")
data = tomllib.loads(p.read_text(encoding="utf-8"))
print(data.get("project", {}).get("version", "UNKNOWN"))
'@
    Push-Location $Root
    try {
        $meta.Add(($versionCode | & $python - 2>&1 | Out-String).Trim())
    }
    finally {
        Pop-Location
    }
    $meta.Add("")
    $meta.Add("PIP CHECK:")
    $meta.Add((& $python -m pip check 2>&1 | Out-String).Trim())
    $meta.Add("")
    $meta.Add("KEY PACKAGES:")
    foreach ($pkg in @(
        "pyinstaller","pyright","ruff","playwright","PySide6",
        "paddleocr","paddlex","paddlepaddle","opencv-contrib-python",
        "PyMuPDF","Pillow","PyYAML"
    )) {
        $line = & $python -m pip show $pkg 2>$null |
            Select-String -Pattern '^(Name|Version):' |
            ForEach-Object { $_.Line }
        if ($line) {
            $meta.Add(($line -join " | "))
        }
    }
    $meta.Add("")
}

$meta.Add("FILES:")
$meta | Set-Content -LiteralPath $manifest -Encoding UTF8

Get-ChildItem -LiteralPath $stage -Recurse -File |
    Where-Object { $_.FullName -ne $manifest } |
    Sort-Object FullName |
    ForEach-Object {
        $rel = $_.FullName.Substring($stage.Length).TrimStart('\')
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        Add-Content -LiteralPath $manifest -Encoding UTF8 -Value ("{0}`t{1}`t{2}" -f $hash, $_.Length, $rel)
    }

if (Test-Path $zip) {
    Remove-Item $zip -Force
}

Compress-Archive `
    -Path (Join-Path $stage "*") `
    -DestinationPath $zip `
    -CompressionLevel Optimal

$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash

Write-Host ""
Write-Host "RELEASE BASELINE SNAPSHOT COMPLETE" -ForegroundColor Green
Write-Host "ZIP    : $zip"
Write-Host "SHA256 : $zipHash"
Write-Host ""
Write-Host "Excluded sensitive/runtime data: local.yaml, .env, .venv, runtime, DBs, PDFs, logs, backups, dist, release."
