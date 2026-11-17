"""Modelo comentado do config.yaml gerado por `nlr config criar`."""

PRESETS = {
    "ollama": {"base_url": "", "modelo_chat": "auto", "modelo_embeddings": "auto"},
    "lmstudio": {"base_url": "", "modelo_chat": "auto", "modelo_embeddings": "auto"},
    "llamacpp": {"base_url": "", "modelo_chat": "auto", "modelo_embeddings": ""},
    "openai_compat": {"base_url": "https://openrouter.ai/api/v1", "modelo_chat": "",
                      "modelo_embeddings": ""},
}

MODELO = r'''# ==========================================================================================
# Neuron Local Research (NLR) — configuração (YAML). Linhas com # são comentários.
# Depois de editar, rode:  nlr doctor        (ou: iniciar.bat doctor)
# ==========================================================================================

# Idioma da interface e das respostas: pt (português do Brasil) | en (English)
idioma: {idioma}

# Novo chat automático: quando a conversa chega a ~80% do contexto, o NLR resume e continua num chat novo
handoff:
  ativado: true
  limite: 0.8

modelo:
  # Servidor de modelos: ollama | lmstudio | llamacpp | openai_compat
  backend: {backend}
  # Vazio = endereço padrão do backend (ollama :11434, lmstudio :1234, llamacpp :8080)
  base_url: "{base_url}"
  # Modelo principal. "auto" = usa o modelo CARREGADO no servidor; se nenhum estiver carregado, escolhe o
  # maior que cabe no seu PC e avisa. Para fixar, copie o nome exato de `nlr modelos`.
  modelo_chat: "{modelo_chat}"
  # Opcional: modelo menor para tarefas simples (vazio = usa o principal)
  modelo_rapido: ""
  modelo_visao: ""  # modelo com visão para analisar imagens (vazio = usa modelo_chat)
  # Embeddings (biblioteca e memória). "auto" = detecta (ex.: text-embedding-nomic-embed-text-v1.5 no LM Studio)
  modelo_embeddings: "{modelo_embeddings}"
  # Só para APIs na nuvem: NOME da variável no arquivo .env que guarda a chave (nunca a chave aqui!)
  api_key_env: "{api_key_env}"
  temperatura: 0.2
  max_tokens: 2048
  # Contexto. Com contexto_auto: true o NLR lê o valor REAL do servidor (LM Studio: Context Length ao
  # carregar; Ollama: num_ctx/OLLAMA_CONTEXT_LENGTH) e usa este número só se não conseguir ler.
  contexto_tokens: 8192
  contexto_auto: true
  # auto | pequeno | medio | grande  (auto = pelo tamanho do modelo: <5B pequeno, 5-15B médio, >15B grande)
  perfil: auto
  timeout: 300
  # auto | json_schema | json_object | texto  (auto tenta JSON Schema e rebaixa se o servidor recusar)
  saida_estruturada: auto
  # json (padrão, mais robusto em modelos pequenos) | nativo (tool calling do servidor)
  modo_ferramentas: json
  tentativas_json: 3
  mostrar_raciocinio: false
  # Modelos que "pensam" antes de responder (Qwen3.5, Gemma 4...). false = desliga o pensamento:
  # respostas muito mais rápidas e JSON mais confiável. Ligue (true) para tarefas difíceis.
  pensar: false
  # Parâmetros extras enviados ao servidor (extra_body). Ex.: {{"top_k": 20}}
  parametros_extras: {{}}

# Reserva na nuvem (opcional): usada só quando o servidor local não responde.
fallback:
  ativado: false
  backend: openai_compat
  base_url: https://openrouter.ai/api/v1
  modelo_chat: ""
  api_key_env: OPENROUTER_API_KEY
  usar_para_embeddings: false
  modelo_embeddings: ""

biblioteca:
  # Pastas com seus documentos. Use / ou \\ no Windows, ex.: "C:/Users/SeuNome/Documents/Biblioteca"
  pastas: []
  tamanho_trecho: 1200
  sobreposicao: 200
  max_arquivo_mb: 50
  # backend = vetores pelo servidor de modelos | nenhum = só palavras-chave (BM25)
  embeddings: backend
  # nenhum | fastembed (reranqueador local em CPU; pip install fastembed)
  reranker: leve          # leve (sem dependências) | fastembed | nenhum
  ocr: auto               # PDFs escaneados: auto | rapidocr | tesseract | nenhum (pip install -e ".[documentos]")
  k: 8

web:
  # ddgs (DuckDuckGo e outros, sem chave) | searxng (seu próprio buscador)
  motor: ddgs
  searxng_url: ""
  regiao: br-pt
  max_resultados: 6
  paginas_para_ler: 3
  cache_horas: 24

memoria:
  extrair_automaticamente: true
  max_lembrancas_no_contexto: 6

projetos:
  pasta: projetos
  max_tarefas: 12
  max_passos_por_tarefa: 10
  max_tentativas_revisao: 2
  pesquisar_antes_de_planejar: true

seguranca:
  # false = TODO comando pede confirmação. true = comandos da lista abaixo rodam sem perguntar.
  modo_autonomo: false
  comandos_permitidos: [python, python3, py, pytest, "python -m pytest", "pip list", "pip show", node, "npm test",
                        "npm run", "git status", "git diff", "git log", "git init", "git add", "git commit", ls, dir, echo]
  # Expressões regulares extras para bloquear sempre
  comandos_bloqueados: []
  timeout_comando: 120
  # Pastas extras que o agente pode LER (escrever, só na pasta do projeto)
  pastas_extra_leitura: []
  # local | docker (isola comandos num contêiner sem rede; precisa do Docker Desktop)
  execucao: local
  imagem_docker: python:3.12-slim

# Servidores MCP (mesmo formato do mcp.json do LM Studio). Exemplo comentado:
mcp:
  servidores: {{}}
  #  local-agent:
  #    command: "C:/caminho/local-agent/.venv/Scripts/python.exe"
  #    args: ["C:/caminho/local-agent/mcp_server.py"]
  #    permissao: confirmar   # ou livre

plugins:
  pastas: [plugins]

kits:
  pixel:
    ativo: false
    aseprite: ""
    paleta_padrao: db32
  abnt:
    ativo: false
    norma_citacao: "2023"
    fonte: Times New Roman

ui:
  host: 127.0.0.1
  porta: 7860

pasta_dados: dados
'''


def gerar(backend: str = "ollama", modelo_chat: str = "", idioma: str = "pt") -> str:
    p = PRESETS.get(backend, PRESETS["ollama"])
    return MODELO.format(idioma="en" if idioma.lower().startswith("en") else "pt", backend=backend, base_url=p["base_url"], modelo_chat=modelo_chat or p["modelo_chat"],
                         modelo_embeddings=p["modelo_embeddings"],
                         api_key_env="OPENROUTER_API_KEY" if backend == "openai_compat" else "")
