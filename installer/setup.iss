; InfluxDB Manager 1.4.1 — Inno Setup script
; Produces dist\InfluxDBManager-Setup-1.4.1.exe

#define MyAppName      "InfluxDB Manager"
#define MyAppVersion   "1.4.1"
#define MyAppPublisher "net.sakurain"
#define MyAppURL       "https://github.com/IYeaSakura/InfluxDB-Manager"
#define MyAppExeName   "InfluxDBManager.exe"

[Setup]
AppId={{B7A1C9E2-4F3D-4A5B-9C6E-2D8F1A3B4C5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Output
OutputDir=D:\CodeLab\InfluxDBStudio\dist
OutputBaseFilename=InfluxDBManager-Setup-1.4.1
; Compression: maximum, solid
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
; Icon
SetupIconFile=D:\CodeLab\InfluxDBStudio\sakurain.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; Misc
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
CloseApplications=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english";    MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "D:\CodeLab\InfluxDBStudio\dist_slim\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Keep user settings under %APPDATA%\InfluxDBStudio (same policy as the C# original)
