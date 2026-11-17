@echo off
rem Atalho do Neuron Local Research: abre a interface web no navegador.
cd /d "%~dp0"
if not exist ".venv\Scripts\nlr.exe" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalador\primeira-execucao.ps1"
set NLR_CONFIG=%APPDATA%\NLR\config.yaml
start "" /min ".venv\Scripts\nlr.exe" -c "%NLR_CONFIG%" ui
