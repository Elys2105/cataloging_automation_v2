param(
    [string]$Root = "D:\DACN\JOB2\cataloging_automation_v2",
    [string]$InstallDir = "$env:ProgramFiles\Automation bien muc tai lieu"
)
$ErrorActionPreference = "Stop"
$Version = "0.1.27.4.18"
$Setup = Join-Path $Root "release\AutomationBienMuc-Setup-$Version.exe"
$InstalledExe = Join-Path $InstallDir "AutomationBienMuc.exe"
$DataRoot = Join-Path $env:LOCALAPPDATA "KhoLuuTruAutomation"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Results = Join-Path $Root ("runtime\final-customer-acceptance-0127418\" + $stamp)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object -TypeName System.Security.Principal.WindowsPrincipal -ArgumentList $identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Run PowerShell as Administrator." }
New-Item -ItemType Directory -Force -Path $Results | Out-Null
if (-not (Test-Path -LiteralPath $Setup -PathType Leaf)) { throw "Setup missing: $Setup" }
Get-Process AutomationBienMuc -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
$Sentinel = Join-Path $DataRoot "FINAL_CUSTOMER_RELEASE_PRESERVE.txt"
$SentinelValue = "preserve-$stamp"
Set-Content -LiteralPath $Sentinel -Value $SentinelValue -Encoding UTF8
$uninstaller = Get-ChildItem -LiteralPath $InstallDir -Filter "unins*.exe" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($uninstaller) {
    Write-Host "[FINAL ACCEPTANCE] remove previous binaries" -ForegroundColor Cyan
    $p = Start-Process -FilePath $uninstaller.FullName -ArgumentList @("/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART") -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Previous uninstall failed: $($p.ExitCode)" }
    $deadline=(Get-Date).AddSeconds(90)
    while ((Test-Path -LiteralPath $InstalledExe) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 750 }
    if (Test-Path -LiteralPath $InstalledExe) { throw "Previous installed EXE still exists." }
    Start-Sleep -Seconds 2
}
if ((Get-Content $Sentinel -Raw).Trim() -ne $SentinelValue) { throw "User data preservation failed before install." }
Write-Host "[FINAL ACCEPTANCE] install final setup" -ForegroundColor Cyan
$log=Join-Path $Results "install.log"
$p=Start-Process -FilePath $Setup -ArgumentList @("/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/LOG=$log") -Wait -PassThru
if ($p.ExitCode -ne 0) { if(Test-Path $log){Get-Content $log -Tail 160}; throw "Installer failed: $($p.ExitCode)" }
if (-not (Test-Path -LiteralPath $InstalledExe -PathType Leaf)) { throw "Installed EXE missing." }
if ((Get-Content $Sentinel -Raw).Trim() -ne $SentinelValue) { throw "LocalAppData was not preserved." }
$browser=Get-ChildItem -LiteralPath (Join-Path $InstallDir "_internal\resources\playwright-browsers") -Recurse -Filter chrome.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1
if(-not $browser){throw "Bundled Chromium missing from installed app."}
foreach($slot in 1,2){
 $report=Join-Path $Results ("slot{0}.json" -f $slot)
 $p=Start-Process -FilePath $InstalledExe -ArgumentList @("--slot","$slot","--self-check","--report",$report) -Wait -PassThru
 if($p.ExitCode -ne 0 -or -not(Test-Path $report)){throw "Self-check failed Slot $slot"}
 $j=Get-Content $report -Raw|ConvertFrom-Json
 if(-not $j.ok){$j|ConvertTo-Json -Depth 10|Write-Host;throw "Self-check blockers Slot $slot"}
 if([string]$j.version -ne $Version){throw "Slot ${slot} version mismatch: $($j.version)"}
 if([string]::IsNullOrWhiteSpace([string]$j.bundled_browser)){throw "Slot $slot did not detect bundled browser"}
}
Write-Host "[FINAL ACCEPTANCE] real bundled-browser launch Slot 1/2" -ForegroundColor Cyan
foreach($slot in 1,2){
 $report=Join-Path $Results ("browser-smoke-slot{0}.json" -f $slot)
 $p=Start-Process -FilePath $InstalledExe -ArgumentList @("--slot","$slot","--browser-smoke","--report",$report) -Wait -PassThru
 if($p.ExitCode -ne 0 -or -not(Test-Path $report)){throw "Browser smoke failed Slot $slot"}
 $j=Get-Content $report -Raw|ConvertFrom-Json
 if(-not $j.ok){$j|ConvertTo-Json -Depth 10|Write-Host;throw "Bundled Chromium launch failed Slot ${slot}: $($j.error)"}
}
$shortcutRoots=@([Environment]::GetFolderPath("Desktop"),[Environment]::GetFolderPath("CommonDesktopDirectory"),[Environment]::GetFolderPath("Programs"),[Environment]::GetFolderPath("CommonPrograms"))|Where-Object{$_ -and(Test-Path $_)}
function Find-Link([string]$Name){foreach($r in $shortcutRoots){$x=Get-ChildItem -LiteralPath $r -Recurse -Filter ($Name+".lnk") -File -ErrorAction SilentlyContinue|Select-Object -First 1;if($x){return $x.FullName}}return $null}
$s1=Find-Link "Automation biên mục tài liệu - Slot 1";$s2=Find-Link "Automation biên mục tài liệu - Slot 2"
if(-not $s1){throw "Slot 1 shortcut missing"};if(-not $s2){throw "Slot 2 shortcut missing"}
$summary=@("FINAL_CUSTOMER_ACCEPTANCE_PASS","VERSION=$Version","INSTALL_DIR=$InstallDir","BUNDLED_BROWSER=$($browser.FullName)","SLOT1_SHORTCUT=$s1","SLOT2_SHORTCUT=$s2","USER_DATA_PRESERVED=True","BROWSER_SMOKE_SLOT1=True","BROWSER_SMOKE_SLOT2=True","RESULTS=$Results")
$summary|Set-Content (Join-Path $Results "SUMMARY.txt") -Encoding UTF8
Write-Host "";$summary|ForEach-Object{Write-Host $_}
