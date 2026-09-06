param(
    [string]$Root = "D:\DACN\JOB2\cataloging_automation_v2"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Root)) {
    throw "Project root not found: $Root"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = Join-Path $Root "runtime\audit"
$stage = Join-Path $outDir ("source_snapshot_" + $stamp)
$zip = Join-Path $outDir ("source_snapshot_" + $stamp + ".zip")
$manifest = Join-Path $stage "SOURCE_SNAPSHOT_MANIFEST.txt"

New-Item -ItemType Directory -Force -Path $stage | Out-Null

function Copy-RelFile {
    param([string]$RelativePath)
    $src = Join-Path $Root $RelativePath
    if (-not (Test-Path $src -PathType Leaf)) { return }
    $dst = Join-Path $stage $RelativePath
    $parent = Split-Path -Parent $dst
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Force
}

function Copy-RelTree {
    param([string]$RelativePath)
    $src = Join-Path $Root $RelativePath
    if (-not (Test-Path $src -PathType Container)) { return }

    Get-ChildItem -LiteralPath $src -Recurse -File -Force |
        Where-Object {
            $_.FullName -notmatch '\\__pycache__\\' -and
            $_.Extension -notin @(".pyc", ".pyo") -and
            $_.Name -notmatch '\.bak$' -and
            $_.Name -notmatch '\.backup$'
        } |
        ForEach-Object {
            $rel = $_.FullName.Substring($Root.Length).TrimStart('\')
            $dst = Join-Path $stage $rel
            $parent = Split-Path -Parent $dst
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
        }
}

# Root metadata / entry points.
@(
    "pyproject.toml",
    "run_app.py",
    ".gitignore",
    "README.md"
) | ForEach-Object { Copy-RelFile $_ }

# Safe config only. Never collect config\local.yaml.
@(
    "config\default.yaml",
    "config\local.example.yaml",
    "rules\known_overrides.yaml"
) | ForEach-Object { Copy-RelFile $_ }

# Current production source and tests.
Copy-RelTree "src"
Copy-RelTree "tests"

# Build/release tooling. These are code, not runtime/user data.
Copy-RelTree "build"
Copy-RelTree "scripts"
Copy-RelTree "installer"

# Explicitly remove the audit script's old backups if present in staging.
Get-ChildItem -LiteralPath $stage -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match 'before_fixed_' -or
        $_.Name -match '\.bak$'
    } |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Safety gate: these paths must never enter the snapshot.
$forbidden = @(
    "config\local.yaml",
    ".venv",
    "runtime",
    "backup",
    "backups",
    "browser-profile",
    "Chrome",
    "pdf",
    "ocr",
    "logs",
    "artifacts"
)

$bad = Get-ChildItem -LiteralPath $stage -Recurse -Force |
    Where-Object {
        $rel = $_.FullName.Substring($stage.Length).TrimStart('\')
        $forbidden | Where-Object {
            $rel -eq $_ -or $rel.StartsWith($_ + "\", [System.StringComparison]::OrdinalIgnoreCase)
        }
    }

if ($bad) {
    $bad | Select-Object FullName
    throw "Safety gate failed: forbidden runtime/sensitive paths entered snapshot."
}

# Inventory + hashes.
$files = Get-ChildItem -LiteralPath $stage -Recurse -File | Sort-Object FullName
@(
    "CATALOGING AUTOMATION SOURCE SNAPSHOT"
    "Root: $Root"
    "Created: $(Get-Date -Format o)"
    "Excluded: .venv, config\local.yaml, runtime, backups, browser profiles, PDFs, OCR cache, logs, artifacts"
    ""
    "FILES:"
) | Set-Content -LiteralPath $manifest -Encoding UTF8

foreach ($f in $files) {
    if ($f.FullName -eq $manifest) { continue }
    $rel = $f.FullName.Substring($stage.Length).TrimStart('\')
    $hash = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
    Add-Content -LiteralPath $manifest -Encoding UTF8 -Value ("{0}`t{1}`t{2}" -f $hash, $f.Length, $rel)
}

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal

$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash

Write-Host ""
Write-Host "SOURCE SNAPSHOT COMPLETE" -ForegroundColor Green
Write-Host "ZIP    : $zip"
Write-Host "SHA256 : $zipHash"
Write-Host ""
Write-Host "This snapshot excludes local.yaml, runtime data, browser profiles, PDFs, OCR caches, logs, and backups."
