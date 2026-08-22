#ifndef AppVersion
  #error AppVersion must be provided by scripts/build-windows-installer.ps1
#endif
#ifndef ProjectUrl
  #error ProjectUrl must be provided by scripts/build-windows-installer.ps1
#endif
#ifndef ReleasesUrl
  #error ReleasesUrl must be provided by scripts/build-windows-installer.ps1
#endif

[Setup]
AppId={{7E4BC1EB-592E-5678-B2EA-EC0187BE6115}
AppName=Elsewise
AppVersion={#AppVersion}
AppPublisher=BTW Team
AppPublisherURL={#ProjectUrl}
AppSupportURL={#ProjectUrl}/issues
AppUpdatesURL={#ReleasesUrl}
DefaultDirName={localappdata}\Programs\Elsewise
DefaultGroupName=Elsewise
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\packages
OutputBaseFilename=Elsewise-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Elsewise.exe
CloseApplications=yes
RestartApplications=no
SetupIconFile=..\generated\elsewise.ico
LicenseFile=..\..\LICENSE

[Tasks]
Name: "addtopath"; Description: "Add the Elsewise command to the user PATH"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\..\dist\frozen\Elsewise\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "elsewise.cmd"; DestDir: "{app}\bin"; Flags: ignoreversion

[Icons]
Name: "{group}\Elsewise"; Filename: "{app}\Elsewise.exe"
Name: "{userdesktop}\Elsewise"; Filename: "{app}\Elsewise.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Elsewise.exe"; Description: "Launch Elsewise"; Flags: nowait postinstall skipifsilent

[Code]
const
  EnvironmentKey = 'Environment';

function NormalizePath(Value: String): String;
begin
  Result := RemoveQuotes(RemoveBackslashUnlessRoot(Value));
end;

function HasPathEntry(PathValue, Entry: String): Boolean;
var
  Item: String;
  Position: Integer;
begin
  Result := False;
  Entry := Lowercase(NormalizePath(Entry));
  while PathValue <> '' do begin
    Position := Pos(';', PathValue);
    if Position = 0 then begin Item := PathValue; PathValue := ''; end
    else begin Item := Copy(PathValue, 1, Position - 1); Delete(PathValue, 1, Position); end;
    if Lowercase(NormalizePath(Item)) = Entry then begin Result := True; Exit; end;
  end;
end;

procedure AddUserPath(Entry: String);
var
  Current: String;
begin
  RegQueryStringValue(HKCU, EnvironmentKey, 'Path', Current);
  if not HasPathEntry(Current, Entry) then begin
    if (Current <> '') and (Current[Length(Current)] <> ';') then Current := Current + ';';
    RegWriteExpandStringValue(HKCU, EnvironmentKey, 'Path', Current + Entry);
  end;
end;

procedure RemoveUserPath(Entry: String);
var
  Current, Updated, Item: String;
  Position: Integer;
begin
  if not RegQueryStringValue(HKCU, EnvironmentKey, 'Path', Current) then Exit;
  Updated := '';
  while Current <> '' do begin
    Position := Pos(';', Current);
    if Position = 0 then begin Item := Current; Current := ''; end
    else begin Item := Copy(Current, 1, Position - 1); Delete(Current, 1, Position); end;
    if (Item <> '') and (Lowercase(NormalizePath(Item)) <> Lowercase(NormalizePath(Entry))) then begin
      if Updated <> '' then Updated := Updated + ';';
      Updated := Updated + Item;
    end;
  end;
  RegWriteExpandStringValue(HKCU, EnvironmentKey, 'Path', Updated);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  if FileExists(ExpandConstant('{app}\elsewise.exe')) then
    Exec(ExpandConstant('{app}\elsewise.exe'), 'stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    AddUserPath(ExpandConstant('{app}\bin'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then begin
    if FileExists(ExpandConstant('{app}\elsewise.exe')) then
      Exec(ExpandConstant('{app}\elsewise.exe'), 'stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    RemoveUserPath(ExpandConstant('{app}\bin'));
  end;
end;
