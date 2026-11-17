@echo off
chcp 65001 >nul
title Neuron Local Research - instalador
echo.
echo  Neuron Local Research (NLR) - instalacao com 1 clique
echo  Nao precisa ter Python: o instalador baixa tudo sozinho (uv + Python 3.12).
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1" %*
pause
