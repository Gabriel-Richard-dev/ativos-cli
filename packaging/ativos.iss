; Instalador do ATIVOS-CLI para Windows (Inno Setup 6).
; Empacota dist\ativos.exe, gerado antes por packaging/build.py, e põe a pasta no PATH.
; Uso: iscc /DAppVersion=1.0.0 packaging\ativos.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{FAE53E99-01E4-4526-8C48-1A0CD7D8E332}
AppName=ATIVOS-CLI
AppVersion={#AppVersion}
AppPublisher=Gabriel Richard
AppPublisherURL=https://github.com/Gabriel-Richard-dev/ativos-cli
DefaultDirName={autopf}\ATIVOS-CLI
DisableDirPage=yes
DisableProgramGroupPage=yes
; Instala só para o usuário atual, sem pedir administrador (o usuário pode escolher).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesEnvironment=yes
OutputDir=..\dist
OutputBaseFilename=ativos-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
UninstallDisplayName=ATIVOS-CLI
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "..\dist\ativos.exe"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
; PATH do usuário (instalação sem administrador) ou do sistema (com administrador).
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; Check: not IsAdminInstallMode and NeedsAddPath(ExpandConstant('{app}'))
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
  ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
  Check: IsAdminInstallMode and NeedsAddPath(ExpandConstant('{app}'))

[Code]
function PathKey(var Root: Integer): String;
begin
  if IsAdminInstallMode then begin
    Root := HKEY_LOCAL_MACHINE;
    Result := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';
  end else begin
    Root := HKEY_CURRENT_USER;
    Result := 'Environment';
  end;
end;

function NeedsAddPath(Dir: String): Boolean;
var
  Root: Integer;
  Key, Paths: String;
begin
  Key := PathKey(Root);
  if not RegQueryStringValue(Root, Key, 'Path', Paths) then begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') = 0;
end;

procedure RemovePath(Dir: String);
var
  Root, P: Integer;
  Key, Paths: String;
begin
  Key := PathKey(Root);
  if not RegQueryStringValue(Root, Key, 'Path', Paths) then
    exit;
  Paths := ';' + Paths + ';';
  P := Pos(';' + Uppercase(Dir) + ';', Uppercase(Paths));
  if P = 0 then
    exit;
  Delete(Paths, P, Length(Dir) + 1);
  Paths := Copy(Paths, 2, Length(Paths) - 2);
  RegWriteExpandStringValue(Root, Key, 'Path', Paths);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemovePath(ExpandConstant('{app}'));
end;
