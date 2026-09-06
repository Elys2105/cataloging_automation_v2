param(
    [Parameter(Mandatory=$true)][string]$Backup,
    [string]$InstallDir = "$env:ProgramFiles\Automation bien muc tai lieu"
)

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object -TypeName System.Security.Principal.WindowsPrincipal -ArgumentList $identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Rollback requires PowerShell Administrator."
}

if (Get-Process -Name "AutomationBienMuc" -ErrorAction SilentlyContinue) {
    throw "Close AutomationBienMuc before rollback."
}

$map = @{
    "AutomationBienMuc.exe" = (Join-Path $InstallDir "AutomationBienMuc.exe")
    "_internal\pyproject.toml" = (Join-Path $InstallDir "_internal\pyproject.toml")
    "_internal\config\default.yaml" = (Join-Path $InstallDir "_internal\config\default.yaml")
}

foreach ($rel in $map.Keys) {
    $src = Join-Path $Backup $rel
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) {
        throw "Backup file missing: $src"
    }
    Copy-Item -LiteralPath $src -Destination $map[$rel] -Force
}

Write-Host "INSTALLED_ROLLBACK_COMPLETE" -ForegroundColor Green
