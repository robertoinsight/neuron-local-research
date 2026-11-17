#!/usr/bin/env bash
# Inicia o Neuron Local Research. Sem argumentos abre a interface web; com argumentos repassa para a CLI.
# Exemplos: ./iniciar.sh            ./iniciar.sh chat            ./iniciar.sh projeto listar
set -e
cd "$(dirname "$0")"
[ -x .venv/bin/nlr ] || { echo "Rode primeiro: ./instalar.sh"; exit 1; }
if [ "$(grep -E '^\s*backend:' config.yaml 2>/dev/null | head -1 | awk '{print $2}' | tr -d '"')" = "ollama" ] \
   && command -v ollama >/dev/null 2>&1 && ! curl -fs http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  echo "Iniciando o Ollama..."; (nohup ollama serve >/tmp/ollama-serve.log 2>&1 &); sleep 3
fi
if [ $# -eq 0 ]; then exec .venv/bin/nlr ui; else exec .venv/bin/nlr "$@"; fi
