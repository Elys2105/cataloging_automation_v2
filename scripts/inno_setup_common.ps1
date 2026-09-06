function Get-InnoSetupCompilerPath {
    [CmdletBinding()]
    param()

    $candidates = New-Object System.Collections.Generic.List[string]

    function Add-Candidate {
        param([string]$Path)
        if ([string]::IsNullOrWhiteSpace($Path)) { return }
        $expanded = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
        if (-not $candidates.Contains($expanded)) {
            $candidates.Add($expanded)
        }
    }

    foreach ($base in @(
        ${env:ProgramFiles(x86)},
        $env:ProgramFiles,
        $env:LOCALAPPDATA
    )) {
        if (-not [string]::IsNullOrWhiteSpace($base)) {
            if ($base -eq $env:LOCALAPPDATA) {
                Add-Candidate (Join-Path $base "Programs\Inno Setup 6\ISCC.exe")
                Add-Candidate (Join-Path $base "Inno Setup 6\ISCC.exe")
            }
            else {
                Add-Candidate (Join-Path $base "Inno Setup 6\ISCC.exe")
            }
        }
    }

    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source) {
        Add-Candidate $command.Source
    }

    foreach ($appPathKey in @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe"
    )) {
        try {
            $item = Get-ItemProperty -LiteralPath $appPathKey -ErrorAction Stop
            Add-Candidate $item.'(default)'
            Add-Candidate $item.Path
        }
        catch {
            # Registry view/key may not exist on this machine.
        }
    }

    foreach ($uninstallRoot in @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )) {
        try {
            foreach ($key in Get-ChildItem -LiteralPath $uninstallRoot -ErrorAction Stop) {
                try {
                    $item = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction Stop
                    $displayName = [string]$item.DisplayName
                    if ($displayName -notmatch '^Inno Setup 6(\b|$)') { continue }

                    if ($item.InstallLocation) {
                        Add-Candidate (Join-Path ([string]$item.InstallLocation) "ISCC.exe")
                    }

                    if ($item.DisplayIcon) {
                        $iconPath = ([string]$item.DisplayIcon -split ',')[0].Trim().Trim('"')
                        if ($iconPath) {
                            $iconDir = Split-Path -Parent $iconPath
                            if ($iconDir) {
                                Add-Candidate (Join-Path $iconDir "ISCC.exe")
                            }
                        }
                    }

                    if ($item.UninstallString) {
                        $uninstall = [string]$item.UninstallString
                        $match = [regex]::Match($uninstall, '^\s*"?(?<exe>[^"]+?unins\d*\.exe)"?(?:\s|$)', 'IgnoreCase')
                        if ($match.Success) {
                            $installDir = Split-Path -Parent $match.Groups['exe'].Value
                            if ($installDir) {
                                Add-Candidate (Join-Path $installDir "ISCC.exe")
                            }
                        }
                    }
                }
                catch {
                    # Ignore malformed/unreadable uninstall entries.
                }
            }
        }
        catch {
            # Registry root/view may not exist.
        }
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            try {
                return (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).Path
            }
            catch {
                return $candidate
            }
        }
    }

    return $null
}
