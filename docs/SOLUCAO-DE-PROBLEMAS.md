# Solução de problemas

Comece sempre por:

```bash
nlr doctor            # Windows: iniciar.bat doctor
agente -v <comando>      # -v mostra pensamentos, chamadas de ferramenta e observações
```

## Servidor de modelos

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| "Não consegui conectar ao servidor de modelos 'ollama' em http://localhost:11434/v1" | Ollama fechado | Abra o app do Ollama ou rode `ollama serve`. `iniciar.bat` tenta iniciá-lo sozinho. |
| Idem com `lmstudio` / porta 1234 | Servidor do LM Studio desligado | LM Studio → Developer → **Start Server**, ou `lms server start`. |
| "modelo 'qwen3.5:9b' não encontrado" | Modelo não baixado / nome diferente | `ollama pull qwen3.5:9b` ou corrija `modelo.modelo_chat` (o `doctor` lista os modelos do servidor). |
| "demorou demais (limite de 300s)" | Modelo grande demais para a VRAM, contexto alto ou CPU | `ollama ps`: se não estiver "100% GPU", use `qwen3.5:4b`/`gemma4:e4b`, reduza `contexto_tokens`, aumente `modelo.timeout`. |
| Respostas muito lentas e cheias de "Thinking Process" | Modo "pensamento" ligado | `modelo.pensar: false` (padrão). No LM Studio, desligue "Thinking" nas configurações do modelo. |
| "O modelo não devolveu JSON válido" | Modelo pequeno/quantizado demais | Use um modelo ≥ 4B; mantenha `modo_ferramentas: json`; aumente `tentativas_json`; `saida_estruturada: json_schema` se o servidor suportar. |
| Falta de memória da GPU (CUDA out of memory) | Contexto alto + modelo de embeddings + chat juntos | Reduza `OLLAMA_CONTEXT_LENGTH`/Context Length; use quantização Q4_K_M; feche jogos/Blender. |

## Biblioteca

| Sintoma | O que fazer |
|---|---|
| "A biblioteca está vazia/não indexada" | `nlr biblioteca adicionar <pasta>` e `nlr indexar`. |
| PDF sem trechos | É escaneado (imagem). Passe OCR (ex.: `ocrmypdf entrada.pdf saida.pdf`). |
| "embeddings indisponíveis — indexado só por palavras-chave" | Baixe o modelo de embeddings (`ollama pull qwen3-embedding:0.6b`; no LM Studio carregue um modelo de embedding) e rode `nlr indexar --vetores`. |
| Busca não acha algo que existe | Teste com `nlr biblioteca buscar "termo"`; confira `biblioteca.extensoes`/`ignorar`/`max_arquivo_mb`; `nlr indexar --forcar`. |
| Acentos estranhos em .txt antigos | O carregador tenta UTF-8 e depois Windows-1252; salve o arquivo como UTF-8 se persistir. |

## Web

| Sintoma | O que fazer |
|---|---|
| "a busca falhou / limite de requisições" | O DuckDuckGo limita rajadas. Espere 1 minuto; o cache (`web.cache_horas`) evita repetições. Para uso pesado, rode um SearXNG (`web.motor: searxng`). |
| Página sem texto | Sites com muito JavaScript não são lidos pelo trafilatura; o agente usa o resumo da busca. |

## Projetos

| Sintoma | O que fazer |
|---|---|
| Projeto parou no meio (Ctrl+C, queda de energia) | `nlr projeto listar` → `nlr projeto retomar <id>`. |
| "PERMISSÃO NEGADA: ... precisa de confirmação" | Comando fora do modo autônomo num terminal não interativo (ou pela interface web). Rode pela CLI num terminal normal para aprovar, ou use `--autonomo` (só comandos da lista). |
| Tarefa marcada `[!]` | Falhou na revisão após as tentativas. Leia `DIARIO.md`, corrija à mão ou peça: `nlr projeto continuar <id> "corrija a tarefa 2: ..."`. |
| O modelo usa bibliotecas que você não tem (ex.: pandas) | Diga no objetivo "use só a biblioteca padrão", ou instale no seu Python. |
| Plano ruim / tarefas demais | Modelos pequenos planejam pior: use o 9b, reduza `projetos.max_tarefas`, escreva o objetivo com mais detalhes. |

## Windows

| Sintoma | O que fazer |
|---|---|
| "a execução de scripts foi desabilitada neste sistema" | Use os `.bat` (eles chamam o PowerShell com `-ExecutionPolicy Bypass` só para o script). |
| `python` abre a Microsoft Store | Instale o Python de python.org e desative os "aliases de execução de aplicativo" do Python em Configurações. |
| Acentos quebrados no terminal | Os `.bat` já usam `chcp 65001`. No Windows Terminal, use a fonte Cascadia. |
| Antivírus bloqueando o `.venv` | Adicione a pasta do agente às exclusões (o pip cria muitos executáveis). |

## Recomeçar do zero

Apague a pasta `dados/` (memória, índice, checkpoints) — seus documentos e os projetos em `projetos/` não são tocados. Para reinstalar as dependências, apague `.venv/` e rode o instalador.

## "não carregado" / "pronto (carrega ao usar)" no topo da interface
- Na v0.4 o aviso ficava preso em "não carregado": a lista de modelos era lida uma vez, antes de o modelo carregar. A v0.5 corrigiu isso.
- Hoje "pronto (carrega ao usar)" é normal no Ollama e no LM Studio (com JIT): o modelo foi descarregado por inatividade e volta a carregar na próxima pergunta.
- O aviso atualiza sozinho após cada resposta e a cada 60 s.

## PDF "sem texto extraível"
O PDF é escaneado e não há OCR instalado. Instale com `pip install -e ".[documentos]"` (no Windows: `instalar.ps1 -ComDocumentos`) e rode `nlr indexar --forcar`.
`nlr biblioteca documentos` mostra quais páginas foram lidas por OCR.
