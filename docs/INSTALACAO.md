# Instalação

> **NLR 0.3:** o instalador `instalar.bat` agora usa o **uv** e baixa o Python sozinho, detecta se o LM Studio, o Ollama ou o llama.cpp está ligado e pergunta o idioma. Para o LM Studio, o jeito mais simples está em [LM-STUDIO.md](LM-STUDIO.md). As opções antigas (`-Backend`, `-Modelo`, `-SemOllama`) do instalador do Ollama foram simplificadas: com Ollama, baixe o modelo com `ollama pull <modelo>` antes ou depois de instalar.

Requisitos: **Python 3.10 ou mais novo** (recomendado 3.12), ~2 GB livres para o programa e 1–7 GB por modelo. Funciona sem GPU (mais devagar). Testado de verdade em Linux; os scripts de Windows foram escritos e verificados quanto à sintaxe, mas **não foram executados num Windows real** (veja o fim deste arquivo).

## Windows (o seu caso: 24 GB de RAM, GPU de 8 GB)

1. Instale o **Python 3.12**: https://www.python.org/downloads/ — marque **"Add python.exe to PATH"**. (Ou: `winget install -e --id Python.Python.3.12`.)
2. Descompacte `neuron-local-research.zip` numa pasta sem acentos, por exemplo `C:\IA\neuron-local-research`.
3. Dê dois cliques em **`instalar.bat`**. Ele:
   - cria o ambiente virtual `.venv` e instala as dependências;
   - detecta a VRAM com `nvidia-smi` e escolhe o modelo (`qwen3.5:9b` com 8 GB; `qwen3.5:4b` com menos ou sem GPU);
   - instala o **Ollama** (`winget install -e --id Ollama.Ollama`, ou o instalador oficial `irm https://ollama.com/install.ps1 | iex` se o winget falhar);
   - baixa o modelo de chat e o de embeddings `qwen3-embedding:0.6b`;
   - cria o `config.yaml` comentado e o `.env`;
   - roda o diagnóstico (`nlr doctor`).
4. Depois: **`iniciar.bat`** abre a interface web em http://127.0.0.1:7860. `iniciar.bat chat` abre o chat no terminal. Qualquer comando da CLI funciona assim: `iniciar.bat projeto listar`.

Opções do instalador (no PowerShell):

```powershell
.\instalar.bat -Modelo gemma4:e4b          # outro modelo
.\instalar.bat -Backend lmstudio           # usar o LM Studio em vez do Ollama
.\instalar.bat -SemModelos                 # não baixar modelos agora
.\instalar.bat -ComReranker -Testes        # reranker opcional + roda a suíte de testes
```

### Usando o LM Studio (que você já tem)

1. No LM Studio, baixe um modelo de chat (ex.: **Qwen3.5 9B** ou **Gemma 4 E4B**, quantização Q4_K_M) e um de embeddings (ex.: **Qwen3 Embedding 0.6B** ou **nomic-embed-text-v2**).
2. Aba **Developer → Start Server** (porta 1234), ou no terminal: `lms server start` e `lms load <modelo>`.
3. Ao carregar o modelo, ajuste **Context Length** para 8192 ou mais (combine com `modelo.contexto_tokens`).
4. Instale com `instalar.bat -Backend lmstudio`. O `config.yaml` virá com `modelo_chat: "auto"` (usa o modelo carregado). Para fixar, copie o nome exato que aparece em `nlr doctor`.

### Ollama: dicas para 8 GB de VRAM

- Contexto: defina a variável de ambiente `OLLAMA_CONTEXT_LENGTH=8192` (ou 16384 com o 4b) e reinicie o Ollama.
- `ollama ps` mostra se o modelo está 100% na GPU. Se aparecer "CPU/GPU", use um modelo menor.
- Para manter o modelo carregado: `OLLAMA_KEEP_ALIVE=30m`.

## Linux / macOS / WSL

```bash
unzip neuron-local-research.zip && cd neuron-local-research
./instalar.sh                      # Ollama + qwen3.5 (9b com GPU ≥ 8 GB, senão 4b) + qwen3-embedding:0.6b
./instalar.sh --backend lmstudio   # sem Ollama
./instalar.sh --modelo gemma4:e4b --com-reranker --testes
./iniciar.sh                       # interface web
./iniciar.sh chat                  # chat no terminal
```

No Debian/Ubuntu, se faltar o venv: `sudo apt install python3-venv`.

## Instalação manual (qualquer sistema)

```bash
python -m venv .venv
.venv/bin/pip install -e ".[completo]"         # Windows: .venv\Scripts\pip install -e ".[completo]"
ollama pull qwen3.5:9b && ollama pull qwen3-embedding:0.6b
.venv/bin/nlr config criar --backend ollama
.venv/bin/nlr doctor
```

Extras opcionais: `reranker` (fastembed, melhora a ordem dos trechos; baixa ~600 MB na primeira vez), `dev` (gera PDFs de exemplo nos testes).

## Reserva na nuvem (opcional)

Se o servidor local não responder, o agente pode usar uma API. No `.env`:

```
OPENROUTER_API_KEY=sua_chave
```

No `config.yaml`:

```yaml
fallback:
  ativado: true
  backend: openai_compat
  base_url: https://openrouter.ai/api/v1
  modelo_chat: "qwen/qwen3.5-35b-a3b"     # qualquer modelo do provedor
  api_key_env: OPENROUTER_API_KEY
```

Também dá para usar a nuvem como principal: `nlr config criar --backend openai_compat`.

## Onde ficam as coisas

| Caminho | Conteúdo |
|---|---|
| `config.yaml` | Configuração (comentada) |
| `.env` | Chaves de API (não compartilhe) |
| `dados/agente.db` | Memória e conversas |
| `dados/biblioteca.db` | Índice da biblioteca |
| `dados/checkpoints.db` | Pontos de retomada dos projetos |
| `projetos/<id>/` | Cada projeto, com `PLANO.md`, `DIARIO.md`, `RELATORIO.md` |

## O que foi testado

- `instalar.sh` foi executado no Linux (Python 3.13) com `--sem-ollama --sem-modelos` e o Ollama 0.40.13 instalado à parte (o download de modelos pelo `ollama pull` foi bloqueado pela rede do ambiente de teste; os modelos foram importados de arquivos GGUF).
- `instalar.ps1` / `iniciar.ps1` foram verificados com o analisador do PowerShell 7.5.4, mas **não rodaram no Windows**. Se algo falhar, a instalação manual acima funciona igual.
- GPU não foi testada (o teste com modelo real foi na CPU).
