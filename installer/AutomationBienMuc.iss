#ifndef MyAppVersion
  #error MyAppVersion is required
#endif
#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif

#define MyAppName "Automation biên mục tài liệu"
#define MyAppExeName "AutomationBienMuc.exe"

[Setup]
AppId={{5C50F0E2-11DE-4C14-AF39-F5A8EA04B8D2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Internal Automation Team
DefaultDirName={autopf}\Automation bien muc tai lieu
DefaultGroupName=Automation bien muc tai lieu
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
OutputDir={#OutputDir}
OutputBaseFilename=AutomationBienMuc-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
ChangesEnvironment=no
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Automation biên mục tài liệu - Slot 1"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--slot 1"
Name: "{group}\Automation biên mục tài liệu - Slot 2"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--slot 2"
Name: "{autodesktop}\Automation biên mục tài liệu - Slot 1"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--slot 1"
Name: "{autodesktop}\Automation biên mục tài liệu - Slot 2"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--slot 2"

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--slot 1"; Description: "Mở Automation biên mục tài liệu - Slot 1"; Flags: nowait postinstall skipifsilent
