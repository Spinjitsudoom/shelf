; Inno Setup script for Shelf Server on Windows. Build after PyInstaller (and ffmpeg) have
; filled dist\Shelf Server:
;   iscc /DAppVersion=0.6.0 packaging\windows\installer.iss
; It installs for the current user only (no administrator needed), adds Start menu
; shortcuts, and starts Shelf Server at the end.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C0B3D2E-7A51-4F0E-9C61-5E1F0A7B2D44}
AppName=Shelf Server
AppVersion={#AppVersion}
AppPublisher=Spinjitsudoom
AppPublisherURL=https://github.com/Spinjitsudoom/shelf
DefaultDirName={localappdata}\Programs\Shelf Server
DefaultGroupName=Shelf Server
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Shelf-Server-Setup-{#AppVersion}
SetupIconFile=..\..\desktop\build\icon.ico
UninstallDisplayIcon={app}\Shelf Server.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force

[Files]
Source: "..\..\dist\Shelf Server\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Shelf Server"; Filename: "{app}\Shelf Server.exe"
Name: "{group}\Open Shelf"; Filename: "http://localhost:4533/"

[Run]
Filename: "{app}\Shelf Server.exe"; Description: "Start Shelf Server"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/F /IM shelf-server.exe /IM ""Shelf Server.exe"""; Flags: runhidden; RunOnceId: "StopShelf"

[UninstallDelete]
; Settings and the library database (in %LOCALAPPDATA%\Shelf) are kept, so reinstalling
; picks up where it left off. Delete that folder by hand to remove them too.
Type: filesandordirs; Name: "{app}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Shelf Server"; Flags: uninsdeletevalue dontcreatekey
