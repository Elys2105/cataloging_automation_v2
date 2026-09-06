param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent)
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath $Root).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Python environment not found: $Python" }

$ExpectedName = "opencv-contrib-python"
$ExpectedVersion = "4.10.0.84"
$OpenCvNames = @(
    "opencv-python",
    "opencv-python-headless",
    "opencv-contrib-python",
    "opencv-contrib-python-headless"
)

function Get-InstalledOpenCv {
    $raw = & $Python -m pip list --format=json
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect installed packages" }
    $all = $raw | ConvertFrom-Json
    return @($all | Where-Object { $OpenCvNames -contains $_.name.ToLowerInvariant() })
}

$before = @(Get-InstalledOpenCv)
Write-Host "OPENCV BEFORE:" -ForegroundColor Cyan
$before | ConvertTo-Json -Compress | Write-Host

if (
    $before.Count -eq 1 -and
    $before[0].name.ToLowerInvariant() -eq $ExpectedName -and
    $before[0].version -eq $ExpectedVersion
) {
    Write-Host "OPENCV_ALREADY_NORMALIZED" -ForegroundColor Green
    exit 0
}

$restore = @($before | ForEach-Object { $_.name + "==" + $_.version })
$uninstallArgs = @("-m", "pip", "uninstall", "-y") + $OpenCvNames

Write-Host "Removing overlapping OpenCV wheels..." -ForegroundColor Yellow
& $Python @uninstallArgs
if ($LASTEXITCODE -ne 0) { throw "OpenCV uninstall failed" }

try {
    Write-Host "Installing $ExpectedName==$ExpectedVersion ..." -ForegroundColor Yellow
    & $Python -m pip install --no-cache-dir ($ExpectedName + "==" + $ExpectedVersion)
    if ($LASTEXITCODE -ne 0) { throw "OpenCV install failed" }

    & $Python -c "import cv2, importlib.metadata as m; print('cv2='+cv2.__version__); print('dist='+m.version('opencv-contrib-python')); assert m.version('opencv-contrib-python')=='4.10.0.84'; assert hasattr(cv2,'createCLAHE'); assert hasattr(cv2,'findContours')"
    if ($LASTEXITCODE -ne 0) { throw "cv2 runtime smoke failed" }

    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { throw "pip check failed after OpenCV normalization" }
}
catch {
    Write-Host "NORMALIZATION_FAILED - attempting to restore previous OpenCV set" -ForegroundColor Red
    & $Python @uninstallArgs | Out-Null
    if ($restore.Count -gt 0) {
        & $Python -m pip install --no-cache-dir @restore | Out-Host
    }
    throw
}

$after = @(Get-InstalledOpenCv)
Write-Host "OPENCV AFTER:" -ForegroundColor Cyan
$after | ConvertTo-Json -Compress | Write-Host
Write-Host "OPENCV_NORMALIZED" -ForegroundColor Green
