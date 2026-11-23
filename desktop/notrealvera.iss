; VeraChecks for Windows - per-user installer (no admin rights). build.py compiles it with:
;   iscc /DAppVersion=1.0.0 /DSourceDir=<dist\VeraChecks> /DOutputDir=<dist> /DIconFile=<build\notrealvera.ico> notrealvera.iss
; Installs to %LOCALAPPDATA%\Programs\VeraChecks, adds VeraChecks to the Start menu (and optionally the desktop) and lists it
; in Settings > Apps. The window keeps its data (what you saved in it) in %LOCALAPPDATA%\VeraChecks, which
; uninstalling leaves in place so a reinstall finds it again.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\VeraChecks"
#endif
#ifndef OutputDir
  #define OutputDir "dist"
#endif
#ifndef IconFile
  #define IconFile "build\notrealvera.ico"
#endif

[Setup]
AppId={{E81247BA-698B-569E-A6DE-E1E1C366EEFB}
AppName=VeraChecks
AppVersion={#AppVersion}
AppVerName=VeraChecks {#AppVersion}
AppPublisher=Juwen Lie
AppPublisherURL=https://juw12.github.io/not-real-vera/
AppSupportURL=https://github.com/juw12/not-real-vera
DefaultDirName={autopf}\VeraChecks
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=VeraChecks-Windows-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\VeraChecks.exe
UninstallDisplayName=VeraChecks
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\VeraChecks"; Filename: "{app}\VeraChecks.exe"; Comment: "Short videos on scam and deepfake defence"
Name: "{userdesktop}\VeraChecks"; Filename: "{app}\VeraChecks.exe"; Comment: "Short videos on scam and deepfake defence"; Tasks: desktopicon

[Run]
Filename: "{app}\VeraChecks.exe"; Description: "{cm:LaunchProgram,VeraChecks}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\VeraChecks.exe"; Parameters: "--stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopVeraChecks"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  { Updating: close an open VeraChecks window first so its files can be replaced. }
  if FileExists(ExpandConstant('{app}\VeraChecks.exe')) then
    Exec(ExpandConstant('{app}\VeraChecks.exe'), '--stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
