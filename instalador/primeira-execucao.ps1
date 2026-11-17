# Preparação do NLR instalado pelo .exe: Python 3.12 próprio (via uv) + dependências + config em %APPDATA%\NLR.
param([string]$Idioma = "pt")
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$uv = Join-Path $raiz "ferramentas\uv\uv.exe"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $raiz "ferramentas\python"
& $uv python install 3.12
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $uv venv .venv --python 3.12 }
& $uv pip install --python .venv\Scripts\python.exe -e ".[completo]"
if ($LASTEXITCODE) { Write-Host "Falhou instalar as dependências. Verifique a internet e rode NLR de novo." -ForegroundColor Red; exit 1 }
$dados = Join-Path $env:APPDATA "NLR"
New-Item -ItemType Directory -Force -Path $dados | Out-Null
$cfg = Join-Path $dados "config.yaml"
if (-not (Test-Path $cfg)) {
    $backend = "lmstudio"
    try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 2 | Out-Null; $backend = "ollama" } catch { }
    try { Invoke-RestMethod http://127.0.0.1:1234/v1/models -TimeoutSec 2 | Out-Null; $backend = "lmstudio" } catch { }
    & .venv\Scripts\nlr.exe config criar --backend $backend --destino $cfg --idioma-padrao $Idioma
}
Write-Host "Pronto." -ForegroundColor Green
