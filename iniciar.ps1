# Inicia o Neuron Local Research. Sem argumentos abre a interface web; com argumentos repassa para a CLI `nlr`.
# Exemplos:  .\iniciar.ps1      .\iniciar.ps1 chat      .\iniciar.ps1 modelos      .\iniciar.ps1 api
Set-Location -Path $PSScriptRoot
$nlr = ".venv\Scripts\nlr.exe"
if (-not (Test-Path $nlr)) { $nlr = ".venv\Scripts\agente.exe" }
if (-not (Test-Path $nlr)) { Write-Host "Rode primeiro o instalar.bat" -ForegroundColor Red; exit 1 }
$cfg = if (Test-Path "config.yaml") { Get-Content config.yaml -Raw } else { "" }
if ($cfg -match "(?m)^\s*backend:\s*ollama" -and (Get-Command ollama -ErrorAction SilentlyContinue)) {
    try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 2 | Out-Null }
    catch { Write-Host "Iniciando o Ollama..."; Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep 3 }
}
$env:PYTHONIOENCODING = "utf-8"
if ($args.Count -eq 0) { & $nlr ui } else { & $nlr @args }
