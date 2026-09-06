param([string]$Root = "D:\DACN\JOB2\cataloging_automation_v2")
$ErrorActionPreference = "Stop"
$ExpectedVersion = "0.1.27.4.19"
Set-Location -LiteralPath $Root
if (Get-Process -Name "AutomationBienMuc" -ErrorAction SilentlyContinue) { throw "Close Slot 1 and Slot 2 before final build." }
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$version = (& $Python (Join-Path $Root "scripts\read_project_version.py") $Root).Trim()
if ($version -ne $ExpectedVersion) { throw "Expected $ExpectedVersion, found $version" }
Write-Host "[FINAL] Build self-contained customer release" -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\build_windows.ps1") -InstallInnoIfMissing
if ($LASTEXITCODE -ne 0) { throw "Final Windows build failed." }
$Setup = Join-Path $Root "release\AutomationBienMuc-Setup-$ExpectedVersion.exe"
$Portable = Join-Path $Root "release\AutomationBienMuc-Portable-$ExpectedVersion.zip"
$Sums = Join-Path $Root "release\SHA256SUMS.txt"
$BrowserRoot = Join-Path $Root "dist\AutomationBienMuc\_internal\resources\playwright-browsers"
foreach ($p in @($Setup,$Portable,$Sums)) { if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "Missing: $p" } }
$browser = Get-ChildItem -LiteralPath $BrowserRoot -Recurse -Filter chrome.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $browser) { throw "Bundled Chromium missing: $BrowserRoot" }
Write-Host ""
Write-Host "FINAL_BUILD_SUCCESS" -ForegroundColor Green
Write-Host "VERSION         : $ExpectedVersion"
Write-Host "SETUP           : $Setup"
Write-Host "SETUP_SHA256    : $((Get-FileHash $Setup -Algorithm SHA256).Hash)"
Write-Host "PORTABLE        : $Portable"
Write-Host "BUNDLED_BROWSER : $($browser.FullName)"
Write-Host "SHA256SUMS      : $Sums"
Write-Host "NEXT: run scripts\final_customer_acceptance_0127419.ps1 as Administrator"
