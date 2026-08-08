#define MyAppName "Personal Alpha Terminal"
#ifndef MyAppVersion
  #define MyAppVersion "0.9.0"
#endif
#define MyAppPublisher "Personal Alpha Terminal"
#define MyAppExeName "PersonalAlphaTerminal.exe"

[Setup]
AppId={{B4E06B8D-9C99-48A5-96B6-95B42CE64DBD}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\PersonalAlphaTerminal
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release-preview\installer
OutputBaseFilename=PersonalAlphaTerminal-{#MyAppVersion}-ResearchPreview-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Windows Installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\PersonalAlphaTerminal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Personal Alpha Terminal"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Stop Personal Alpha Terminal"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--stop"; WorkingDir: "{app}"
Name: "{group}\Check for updates"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--update"; WorkingDir: "{app}"
Name: "{autodesktop}\Personal Alpha Terminal"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Personal Alpha Terminal"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; User data is intentionally outside {app} and is retained by default.
Type: filesandordirs; Name: "{app}"
