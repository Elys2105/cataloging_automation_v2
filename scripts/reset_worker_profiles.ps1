param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".."))
)

$ErrorActionPreference = "Stop"
$running = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -match 'run_app\.py'
    }
if ($running) {
    throw "Close the automation tool before resetting worker profiles."
}

$workers = Join-Path $ProjectRoot "runtime\workers"
if (Test-Path $workers) {
    Remove-Item $workers -Recurse -Force
}
New-Item -ItemType Directory -Path $workers -Force | Out-Null
Write-Host "Worker profiles removed. They will be cloned from the master login profile on next run." -ForegroundColor Green
