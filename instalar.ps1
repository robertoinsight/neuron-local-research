# Instalador do Neuron Local Research (NLR) para Windows — 1 clique, sem precisar ter Python.
# Usa o uv (https://docs.astral.sh/uv/) baixado para a pasta .\ferramentas\uv, que baixa um Python 3.12
# próprio (não mexe no Python do sistema, não precisa de administrador).
# Uso (opcional):  .\instalar.ps1 [-Backend auto|lmstudio|ollama|llamacpp|openai_compat] [-Idioma pt|en]
#                                 [-ComReranker] [-Testes] [-SemPerguntas]
param(
    [ValidateSet("auto", "ollama", "lmstudio", "llamacpp", "openai_compat")][string]$Backend = "auto",
    [ValidateSet("", "pt", "en")][string]$Idioma = "",
    [switch]$ComReranker,
    [switch]$ComDocumentos,  # OCR (rapidocr) + tabelas de PDF (pdfplumber) — ~150 MB a mais
    [switch]$ComPixel,       # Kit Pixel Art (o Pillow já vem por padrão desde a v0.7)
    [switch]$ComABNT,        # Kit ABNT (python-docx) — ~2 MB
    [switch]$Testes,
    [switch]$SemPerguntas
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-Location -Path $PSScriptRoot
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Titulo($t) { Write-Host "`n== $t ==" -ForegroundColor Green }
function Aviso($t) { Write-Host $t -ForegroundColor Yellow }
function Falha($t) { Write-Host $t -ForegroundColor Red; exit 1 }

if ($PSScriptRoot -match "[^\x00-\x7F]" -or $PSScriptRoot -match " ") {
    Aviso "Dica: a pasta '$PSScriptRoot' tem espaço ou acento. Se algo falhar, mova o NLR para C:\IA\neuron-local-research."
}

if (-not $Idioma) {
    if ($SemPerguntas) { $Idioma = "pt" } else {
        $r = Read-Host "Idioma / Language: [1] Português (padrão)  [2] English"
        $Idioma = if ($r -eq "2") { "en" } else { "pt" }
    }
}

Titulo "1/5 uv (gerenciador de Python)"
$uv = Join-Path $PSScriptRoot "ferramentas\uv\uv.exe"
if (-not (Test-Path $uv)) {
    $sist = Get-Command uv -ErrorAction SilentlyContinue
    if ($sist) { $uv = $sist.Source } else {
        New-Item -ItemType Directory -Force -Path "ferramentas\uv" | Out-Null
        $arq = if ([Environment]::Is64BitOperatingSystem) { "uv-x86_64-pc-windows-msvc.zip" } else { "uv-i686-pc-windows-msvc.zip" }
        if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { $arq = "uv-aarch64-pc-windows-msvc.zip" }
        Write-Host "Baixando $arq ..."
        try {
            Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/$arq" -OutFile "ferramentas\uv\uv.zip"
            Expand-Archive "ferramentas\uv\uv.zip" -DestinationPath "ferramentas\uv" -Force
            Remove-Item "ferramentas\uv\uv.zip"
        } catch { Falha "Não consegui baixar o uv ($_). Verifique a internet/antivírus, ou instale: winget install astral-sh.uv" }
        $achado = Get-ChildItem "ferramentas\uv" -Recurse -Filter uv.exe | Select-Object -First 1
        if (-not $achado) { Falha "uv.exe não encontrado depois de extrair." }
        $uv = $achado.FullName
    }
}
Write-Host ("uv: " + (& $uv --version))

Titulo "2/5 Python 3.12 e dependências (pode levar alguns minutos na 1ª vez)"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot "ferramentas\python"
& $uv python install 3.12; if ($LASTEXITCODE) { Falha "Falhou baixar o Python 3.12." }
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $uv venv .venv --python 3.12; if ($LASTEXITCODE) { Falha "Falhou criar o .venv" } }
$extras = "completo"; if ($ComReranker) { $extras += ",reranker" }; if ($ComDocumentos) { $extras += ",documentos" }; if ($ComPixel) { $extras += ",pixel" }; if ($ComABNT) { $extras += ",abnt" }; if ($Testes) { $extras += ",dev" }
& $uv pip install --python .venv\Scripts\python.exe -e ".[$extras]"
if ($LASTEXITCODE) { Falha "Falhou instalar as dependências (veja a mensagem acima)." }
$nlr = ".venv\Scripts\nlr.exe"

Titulo "3/5 Servidor de modelos"
function No-Ar($url) { try { Invoke-RestMethod $url -TimeoutSec 2 | Out-Null; return $true } catch { return $false } }
if ($Backend -eq "auto") {
    if (No-Ar "http://127.0.0.1:1234/v1/models") { $Backend = "lmstudio"; Write-Host "LM Studio encontrado (porta 1234)." }
    elseif (No-Ar "http://127.0.0.1:11434/api/version") { $Backend = "ollama"; Write-Host "Ollama encontrado (porta 11434)." }
    elseif (No-Ar "http://127.0.0.1:8080/v1/models") { $Backend = "llamacpp"; Write-Host "llama.cpp encontrado (porta 8080)." }
    elseif ($SemPerguntas) { $Backend = "lmstudio" }
    else {
        Aviso "Nenhum servidor de modelos está ligado agora."
        $r = Read-Host "Qual você usa? [1] LM Studio (padrão)  [2] Ollama  [3] llama.cpp  [4] API na nuvem"
        $Backend = @{ "2" = "ollama"; "3" = "llamacpp"; "4" = "openai_compat" }[$r]; if (-not $Backend) { $Backend = "lmstudio" }
    }
}
Write-Host "Backend: $Backend"
if ($Backend -eq "lmstudio") {
    Aviso "LM Studio: carregue um modelo e ligue o servidor (aba Developer > Start Server). O NLR detecta o resto."
}

Titulo "4/5 Configuração"
if (-not (Test-Path "config.yaml")) { & $nlr config criar --backend $Backend --idioma-padrao $Idioma }
else { Write-Host "config.yaml já existe; mantive o seu." }

Titulo "5/5 Diagnóstico"
& $nlr doctor --sem-mcp
if ($Testes) { & .venv\Scripts\python.exe -m pytest -q }

Write-Host "`nPronto! Próximos passos:" -ForegroundColor Green
Write-Host "  - Ver modelos e perfil:       .\iniciar.bat modelos"
Write-Host "  - Chat no terminal:           .\iniciar.bat chat"
Write-Host "  - Interface web:              .\iniciar.bat"
Write-Host "  - Biblioteca:                 .\iniciar.bat biblioteca adicionar `"C:\Users\$env:USERNAME\Documents`"  e depois  .\iniciar.bat indexar"
