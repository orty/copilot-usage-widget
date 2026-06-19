; Copilot Usage Widget — Inno Setup installer
; Build via scripts\build.ps1 or the release CI workflow.

#define MyAppName      "Copilot Usage"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "Serge ARADJ"
#define MyAppExeName   "CopilotUsage.exe"
#define MyAppIcon      "..\assets\icon.ico"
#define MyAppRepo      "https://github.com/SergeARADJ/copilot-usage-widget"

[Setup]
AppId={{B7C4E2A1-F3D5-4891-BCDE-COPILOT00001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppRepo}
AppSupportURL={#MyAppRepo}/issues
AppUpdatesURL={#MyAppRepo}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\releases
OutputBaseFilename=CopilotUsage-Setup
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=force
CloseApplicationsFilter={#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[InstallDelete]
; Clean _internal on update to remove stale DLLs from previous version
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\build\dist\CopilotUsage\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\dist\CopilotUsage\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\{#MyAppName}"
