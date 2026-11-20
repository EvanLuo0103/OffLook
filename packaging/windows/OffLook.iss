[Setup]
AppId=OffLook.EvanLuo0103
AppName=OffLook
AppVersion={#AppVersion}
AppPublisher=EvanLuo0103
DefaultDirName={localappdata}\Programs\OffLook
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DefaultGroupName=OffLook
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=yes
UninstallDisplayIcon={app}\OffLook.exe
OutputDir={#AppOutputDir}
OutputBaseFilename=OffLook-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes

[Tasks]
Name: addpath; Description: "Add ol to the current user's PATH"; Flags: unchecked

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\OffLook"; Filename: "{app}\OffLook.exe"; WorkingDir: "{app}"

[Code]
procedure CurStepChanged(Step: TSetupStep);
var
  ResultCode: Integer;
begin
  if (Step = ssPostInstall) and WizardIsTaskSelected('addpath') then begin
    if not Exec(ExpandConstant('{app}\ol.exe'), 'path add', ExpandConstant('{app}'),
                SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      SuppressibleMsgBox('OffLook installed, but PATH could not be updated. Use Settings > Add to PATH.', mbError, MB_OK, IDOK);
  end;
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
var
  ResultCode: Integer;
begin
  if Step = usUninstall then begin
    if not Exec(ExpandConstant('{app}\ol.exe'), '--installer-remove-integration', ExpandConstant('{app}'),
                SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      SuppressibleMsgBox('Some system integration settings could not be removed. Check PATH and startup settings.', mbError, MB_OK, IDOK);
  end;
end;
