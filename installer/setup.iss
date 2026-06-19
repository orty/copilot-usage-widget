[Setup]
AppName=Copilot Usage
AppVersion=1.0.0
AppPublisher=Serge ARADJ
DefaultDirName={autopf}\CopilotUsage
DefaultGroupName=Copilot Usage
OutputDir=..\releases
OutputBaseFilename=CopilotUsage-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Files]
Source: "..\dist\CopilotUsage.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Copilot Usage"; Filename: "{app}\CopilotUsage.exe"
Name: "{userstartup}\Copilot Usage"; Filename: "{app}\CopilotUsage.exe"

[Run]
Filename: "{app}\CopilotUsage.exe"; Description: "Launch Copilot Usage"; Flags: nowait postinstall skipifsilent
