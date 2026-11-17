#!/usr/bin/env bash
# Instalador do Neuron Local Research (Linux / macOS / WSL).
# Uso: ./instalar.sh [--backend ollama|lmstudio|llamacpp|openai_compat] [--modelo NOME] [--sem-ollama]
#                    [--sem-modelos] [--com-reranker] [--testes]
set -euo pipefail
cd "$(dirname "$0")"

BACKEND="ollama"; MODELO=""; SEM_OLLAMA=0; SEM_MODELOS=0; RERANKER=0; TESTES=0; DOCUMENTOS=0
EMBED="qwen3-embedding:0.6b"
while [ $# -gt 0 ]; do
  case "$1" in
    --backend) BACKEND="$2"; shift 2;;
    --modelo) MODELO="$2"; shift 2;;
    --sem-ollama) SEM_OLLAMA=1; shift;;
    --sem-modelos) SEM_MODELOS=1; shift;;
    --com-reranker) RERANKER=1; shift;;
    --com-documentos) DOCUMENTOS=1; shift;;
    --com-pixel) PIXEL=1; shift;;
    --com-abnt) ABNT=1; shift;;
    --testes) TESTES=1; shift;;
    -h|--help) sed -n 2,4p "$0"; exit 0;;
    *) echo "Opção desconhecida: $1"; exit 1;;
  esac
done

verde() { printf '\033[32m%s\033[0m\n' "$*"; }
amarelo() { printf '\033[33m%s\033[0m\n' "$*"; }
vermelho() { printf '\033[31m%s\033[0m\n' "$*"; }

verde "== 1/5 Python =="
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -z "$PY" ] && { vermelho "Preciso do Python 3.10 ou mais novo. Instale e rode de novo."; exit 1; }
echo "Usando $($PY --version) ($PY)"

verde "== 2/5 Ambiente virtual e dependências =="
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv || { vermelho "Falhou criar o venv. No Debian/Ubuntu: sudo apt install python3-venv"; exit 1; }
fi
.venv/bin/python -m pip install -q --upgrade pip
EXTRAS="completo"; [ "$RERANKER" = 1 ] && EXTRAS="completo,reranker"
[ "$TESTES" = 1 ] && EXTRAS="$EXTRAS,dev"
[ "$DOCUMENTOS" = 1 ] && EXTRAS="$EXTRAS,documentos"
[ "${PIXEL:-0}" = 1 ] && EXTRAS="$EXTRAS,pixel"
[ "${ABNT:-0}" = 1 ] && EXTRAS="$EXTRAS,abnt"
.venv/bin/python -m pip install -q -e ".[${EXTRAS}]"
echo "Dependências instaladas."

verde "== 3/5 Servidor de modelos ($BACKEND) =="
if [ -z "$MODELO" ]; then
  VRAM=0
  if command -v nvidia-smi >/dev/null 2>&1; then
    VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ' || echo 0)
  fi
  if [ "${VRAM:-0}" -ge 7500 ]; then MODELO="qwen3.5:9b"
  elif [ "${VRAM:-0}" -ge 5000 ]; then MODELO="qwen3.5:4b"
  else MODELO="qwen3.5:4b"; amarelo "GPU NVIDIA não detectada: vai rodar na CPU (mais lento). Modelo: $MODELO"; fi
fi
if [ "$BACKEND" = "ollama" ]; then
  if ! command -v ollama >/dev/null 2>&1; then
    if [ "$SEM_OLLAMA" = 1 ]; then
      amarelo "Ollama não encontrado (e --sem-ollama foi usado). Instale depois: https://ollama.com/download"
    elif [ "$(uname)" = "Darwin" ]; then
      amarelo "No macOS instale o Ollama pelo app: https://ollama.com/download (ou: brew install ollama)"
    else
      echo "Instalando o Ollama (script oficial; pode pedir senha do sudo)..."
      curl -fsSL https://ollama.com/install.sh | sh
    fi
  fi
  if command -v ollama >/dev/null 2>&1 && [ "$SEM_MODELOS" = 0 ]; then
    if ! curl -fs http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
      echo "Iniciando 'ollama serve' em segundo plano..."
      (nohup ollama serve >/tmp/ollama-serve.log 2>&1 &); sleep 3
    fi
    echo "Baixando modelos: $MODELO (chat) e $EMBED (embeddings). Isso pode demorar."
    ollama pull "$MODELO" || amarelo "Falhou baixar $MODELO — rode depois: ollama pull $MODELO"
    ollama pull "$EMBED" || amarelo "Falhou baixar $EMBED — rode depois: ollama pull $EMBED"
  fi
else
  amarelo "Backend $BACKEND: abra/inicie o servidor você mesmo (LM Studio: aba Developer > Start Server, ou 'lms server start')."
fi

verde "== 4/5 Configuração =="
if [ ! -f config.yaml ]; then
  if [ "$BACKEND" = "ollama" ]; then
    .venv/bin/nlr config criar --backend ollama --modelo "$MODELO"
  else
    .venv/bin/nlr config criar --backend "$BACKEND"
  fi
else
  echo "config.yaml já existe; mantive o seu."
fi

verde "== 5/5 Diagnóstico =="
.venv/bin/nlr doctor --sem-mcp || true
if [ "$TESTES" = 1 ]; then .venv/bin/python -m pytest -q; fi

verde "Pronto! Próximos passos:"
echo "  1) Adicione sua biblioteca:   .venv/bin/nlr biblioteca adicionar ~/Documentos"
echo "  2) Indexe:                    .venv/bin/nlr indexar"
echo "  3) Converse (terminal):       ./iniciar.sh chat      ou interface web: ./iniciar.sh"
