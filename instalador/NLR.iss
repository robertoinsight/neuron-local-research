; Instalador do Neuron Local Research para Windows (Inno Setup 6).
; Compilar:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" instalador\NLR.iss
; (ou automaticamente pelo GitHub Actions: .github/workflows/instalador-windows.yml)
;
; O .exe é pequeno: leva o código do NLR e o uv.exe. Na primeira execução, o "primeira-execucao.ps1"
; usa o uv para baixar um Python 3.12 próprio e as dependências (precisa de internet uma vez).
; Instala em %LOCALAPPDATA%\Programs\NLR (sem administrador). Dados do usuário ficam em %APPDATA%\NLR.

#define MyAppName "Neuron Local Research"
#define MyAppVersion "0.4.0"
#define MyAppPublisher "Neuron Local Research"
#define MyAppURL "https://github.com/"

[Setup]
AppId={{7B1C3E52-9E2A-4B8B-9C51-4E1E0A6C0F04}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\NLR
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=saida
OutputBaseFilename=NLR-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName}
SetupIconFile=nlr.ico
UninstallDisplayIcon={app}\instalador\nlr.ico
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\nlr\*"; DestDir: "{app}\nlr"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc"
Source: "..\plugins\*"; DestDir: "{app}\plugins"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: recursesubdirs ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.en.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config.exemplo.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\iniciar.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\iniciar.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\instalar.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\instalar.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "primeira-execucao.ps1"; DestDir: "{app}\instalador"; Flags: ignoreversion
Source: "NLR.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "nlr.ico"; DestDir: "{app}\instalador"; Flags: ignoreversion
Source: "uv\uv.exe"; DestDir: "{app}\ferramentas\uv"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\NLR.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\instalador\nlr.ico"
Name: "{autoprograms}\{#MyAppName} (terminal)"; Filename: "{cmd}"; Parameters: "/k ""{app}\iniciar.bat"" chat"; WorkingDir: "{app}"; IconFilename: "{app}\instalador\nlr.ico"
Name: "{autoprograms}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\NLR.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\instalador\nlr.ico"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\instalador\primeira-execucao.ps1"" -Idioma {code:Idioma}"; WorkingDir: "{app}"; StatusMsg: "Preparando Python e dependências (só na primeira vez, alguns minutos)..."; Flags: waituntilterminated
Filename: "{app}\NLR.cmd"; Description: "{cm:LaunchProgram,{#MyAppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\ferramentas"
Type: filesandordirs; Name: "{app}\nlr"

[Code]
function Idioma(Param: String): String;
begin
  if ActiveLanguage = 'en' then Result := 'en' else Result := 'pt';
end;
