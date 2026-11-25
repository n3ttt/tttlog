; tttlog Windows installer (Inno Setup 6). Built by .github/workflows/windows-build.yml:
;   ISCC /DAppVersion=0.1.0a4 /DFileVersion=0.1.0a4-b76 /DSourceDir=..\..\dist\tttlog packaging\windows\tttlog.iss
; Installs for the current user only (no admin prompt) in %LOCALAPPDATA%\Programs\tttlog,
; adds a Start menu entry (desktop icon optional) and an uninstaller in Settings > Apps.
; Logs and settings (Documents\tttlog, %USERPROFILE%\.tttlog) are never touched.
; The in-app updater runs it with /SILENT /RELAUNCH=1: it closes tttlog, updates, reopens it.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef FileVersion
  #define FileVersion AppVersion
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\tttlog"
#endif

[Setup]
AppId={{6C1F3E0A-8E43-4F57-9B5E-7D1A3C0B7A11}
AppName=tttlog
AppVersion={#AppVersion}
AppVerName=tttlog {#FileVersion}
AppPublisher=N3TTT
AppPublisherURL=https://github.com/n3ttt/tttlog
AppSupportURL=https://github.com/n3ttt/tttlog/issues
DefaultDirName={autopf}\tttlog
DefaultGroupName=tttlog
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=tttlog-{#FileVersion}-windows-setup
SetupIconFile=tttlog.ico
UninstallDisplayIcon={app}\tttlog.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
LicenseFile=..\..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; a clean program folder on every update, so files a new build dropped don't linger
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\tttlog"; Filename: "{app}\tttlog.exe"
Name: "{group}\Uninstall tttlog"; Filename: "{uninstallexe}"
Name: "{autodesktop}\tttlog"; Filename: "{app}\tttlog.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\tttlog.exe"; Description: "{cm:LaunchProgram,tttlog}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\tttlog.exe"; Flags: nowait; Check: Relaunch

[Code]
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;
