param(
    [switch]$InstallInnoIfMissing,
    [switch]$SkipInstaller,
    [switch]$InstallerOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $Root

$InnoCommon = Join-Path $Root "scripts\inno_setup_common.ps1"
if (-not (Test-Path -LiteralPath $InnoCommon)) {
    throw "Missing Inno Setup helper: $InnoCommon"
}
. $InnoCommon

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $Python)) { throw "Missing Python environment: $Python" }
if (-not (Test-Path $PyInstaller)) { throw "Missing PyInstaller: $PyInstaller" }

$env:PYTHONPATH = Join-Path $Root "src"
$env:PYTHONNOUSERSITE = "1"

$version = (& $Python scripts\read_project_version.py $Root).Trim()
if (-not $version) { throw "Could not determine project version" }

if (-not $InstallerOnly) {
    Write-Host "[D] Release hardening" -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $Root "scripts\release_hardening.ps1") `
        -Root $Root `
        -FailOnPyright
    if ($LASTEXITCODE -ne 0) { throw "release hardening failed" }

    Write-Host "[D] Stage offline OCR resources" -ForegroundColor Cyan
    & $Python scripts\stage_release_resources.py $Root
    if ($LASTEXITCODE -ne 0) { throw "resource staging failed" }

    Write-Host "[D] Clean generated build output" -ForegroundColor Cyan
    foreach ($path in @(
        (Join-Path $Root "dist"),
        (Join-Path $Root "release\stage")
    )) {
        if (Test-Path $path) { Remove-Item $path -Recurse -Force }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "release") | Out-Null

    Write-Host "[D] PyInstaller onedir" -ForegroundColor Cyan
    $SpecFile = Join-Path $Root "build\CatalogingAutomation.spec"
    $EntryPoint = Join-Path $Root "run_app.py"
    if (-not (Test-Path $SpecFile)) { throw "Missing PyInstaller spec: $SpecFile" }
    if (-not (Test-Path $EntryPoint)) { throw "Missing application entry point: $EntryPoint" }

    $oldModelSourceCheck = $env:DISABLE_MODEL_SOURCE_CHECK
    $pyInstallerExit = 1
    try {
        # PaddleX checks remote model hosts during import/collection unless this is set.
        # The release already stages local OCR models, so network probing is unnecessary.
        $env:DISABLE_MODEL_SOURCE_CHECK = "True"
        & $PyInstaller --clean --noconfirm $SpecFile
        $pyInstallerExit = $LASTEXITCODE
    }
    finally {
        if ($null -eq $oldModelSourceCheck) {
            Remove-Item Env:DISABLE_MODEL_SOURCE_CHECK -ErrorAction SilentlyContinue
        }
        else {
            $env:DISABLE_MODEL_SOURCE_CHECK = $oldModelSourceCheck
        }
    }
    if ($pyInstallerExit -ne 0) { throw "PyInstaller failed" }

    $dist = Join-Path $Root "dist\AutomationBienMuc"
    $exe = Join-Path $dist "AutomationBienMuc.exe"
    if (-not (Test-Path $exe)) { throw "Packaged executable missing: $exe" }

    Write-Host "[D] Packaged self-check Slot 1/2" -ForegroundColor Cyan
    $smokeData = Join-Path $Root "build\smoke-localappdata"
    if (Test-Path $smokeData) { Remove-Item $smokeData -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $smokeData | Out-Null

    $oldLocal = $env:LOCALAPPDATA
    $oldInstalled = $env:CATALOGING_INSTALLED_MODE
    $oldData = $env:CATALOGING_DATA_ROOT
    $oldPythonPath = $env:PYTHONPATH
    try {
        $env:LOCALAPPDATA = $smokeData
        $env:CATALOGING_INSTALLED_MODE = "1"
        $env:CATALOGING_DATA_ROOT = Join-Path $smokeData "KhoLuuTruAutomation"
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue

        foreach ($slot in 1,2) {
            $log = Join-Path $Root ("build\packaged-self-check-slot{0}.json" -f $slot)
            if (Test-Path $log) { Remove-Item $log -Force }
            $process = Start-Process `
                -FilePath $exe `
                -ArgumentList @("--slot", "$slot", "--self-check", "--report", $log) `
                -Wait `
                -PassThru
            if ($process.ExitCode -ne 0 -or -not (Test-Path $log)) {
                if (Test-Path $log) { Get-Content $log }
                throw "Packaged self-check failed for Slot $slot (exit $($process.ExitCode))"
            }
            Get-Content $log
        }
    }
    finally {
        $env:LOCALAPPDATA = $oldLocal
        $env:CATALOGING_INSTALLED_MODE = $oldInstalled
        $env:CATALOGING_DATA_ROOT = $oldData
        $env:PYTHONPATH = $oldPythonPath
    }

    Write-Host "[D] Stage portable/install tree" -ForegroundColor Cyan
    $stage = Join-Path $Root "release\stage\AutomationBienMuc"
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    Copy-Item (Join-Path $dist "*") $stage -Recurse -Force

    $portable = Join-Path $Root ("release\AutomationBienMuc-Portable-{0}.zip" -f $version)
    if (Test-Path $portable) { Remove-Item $portable -Force }
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $portable -CompressionLevel Optimal

}
else {
    Write-Host "[D] Resume installer-only from existing packaged artifacts" -ForegroundColor Cyan

    $dist = Join-Path $Root "dist\AutomationBienMuc"
    $exe = Join-Path $dist "AutomationBienMuc.exe"
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        throw "InstallerOnly requires an existing packaged executable: $exe"
    }

    $stage = Join-Path $Root "release\stage\AutomationBienMuc"
    if (-not (Test-Path -LiteralPath $stage -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $stage | Out-Null
        Copy-Item (Join-Path $dist "*") $stage -Recurse -Force
    }

    $stagedExe = Join-Path $stage "AutomationBienMuc.exe"
    if (-not (Test-Path -LiteralPath $stagedExe -PathType Leaf)) {
        throw "InstallerOnly stage is invalid; missing: $stagedExe"
    }

    $portable = Join-Path $Root ("release\AutomationBienMuc-Portable-{0}.zip" -f $version)
    if (-not (Test-Path -LiteralPath $portable -PathType Leaf)) {
        Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $portable -CompressionLevel Optimal
    }

    Write-Host "EXISTING_EXE      : $exe"
    Write-Host "EXISTING_STAGE    : $stage"
    Write-Host "EXISTING_PORTABLE : $portable"
}

if (-not $SkipInstaller) {
    $iscc = Get-InnoSetupCompilerPath

    if (-not $iscc -and $InstallInnoIfMissing) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass `
            -File (Join-Path $Root "scripts\ensure_inno_setup.ps1")
        $ensureExit = $LASTEXITCODE

        # Resolve again even if winget/ensure returned a non-zero code. The previous
        # build proved that winget can report "already installed/no upgrade" while
        # the compiler is actually available elsewhere.
        $iscc = Get-InnoSetupCompilerPath
        if (-not $iscc -and $ensureExit -ne 0) {
            throw "Unable to make Inno Setup compiler available (ensure exit $ensureExit)"
        }
    }

    if (-not $iscc) {
        throw "Inno Setup 6 compiler (ISCC.exe) not found. Run scripts\ensure_inno_setup.ps1 or rerun with -InstallInnoIfMissing."
    }

    Write-Host "ISCC     : $iscc" -ForegroundColor Green

    Write-Host "[D] Build Inno Setup installer" -ForegroundColor Cyan
    & $iscc `
        "/DMyAppVersion=$version" `
        "/DSourceDir=$stage" `
        "/DOutputDir=$(Join-Path $Root 'release')" `
        (Join-Path $Root "installer\AutomationBienMuc.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }
}

$setup = Join-Path $Root ("release\AutomationBienMuc-Setup-{0}.exe" -f $version)
if (-not $SkipInstaller -and -not (Test-Path $setup)) {
    throw "Installer output missing: $setup"
}

if (-not $SkipInstaller) {
    & $Python scripts\generate_release_docs.py `
        $Root `
        --setup $setup `
        --portable $portable
    if ($LASTEXITCODE -ne 0) { throw "release docs generation failed" }
}

Write-Host ""
Write-Host "BUILD_SUCCESS" -ForegroundColor Green
Write-Host "VERSION  : $version"
Write-Host "EXE      : $exe"
Write-Host "PORTABLE : $portable"
if (-not $SkipInstaller) {
    Write-Host "INSTALLER: $setup"
    Write-Host "SHA256   : $(Join-Path $Root 'release\SHA256SUMS.txt')"
}
