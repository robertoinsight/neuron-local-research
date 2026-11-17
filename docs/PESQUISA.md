# Pesquisa e decisões técnicas (outubro de 2026)

Este documento registra o que foi pesquisado antes de construir o Neuron Local Research, as alternativas avaliadas e o porquê de cada escolha. As versões são as que estavam disponíveis e foram testadas em **29/10/2026**.

## 1. Requisitos que guiaram as escolhas

- Rodar **100% local** num PC com **24 GB de RAM e GPU de 8 GB** (Windows), com CPU como alternativa.
- Modelos pequenos (4–9 B parâmetros) precisam de **saída estruturada robusta** — eles erram JSON com frequência.
- Projetos longos precisam **sobreviver a interrupções** (fechar o terminal, faltar luz) e ser **retomados**.
- Nada de servidores extras para instalar (sem Postgres, Qdrant, Docker obrigatório).
- Tudo em português do Brasil.

## 2. Framework de agentes

| Opção | Versão | Pontos fortes | Pontos fracos para este caso |
|---|---|---|---|
| **LangGraph** | 1.2.18 (+ langgraph-checkpoint-sqlite 3.1.2) | Grafo de estados explícito, *checkpoint* em SQLite a cada passo, retomada nativa (`thread_id`), *human-in-the-loop*, independente de provedor | Mais verboso; puxa `langchain-core` (1.7.1) |
| CrewAI | 1.15.32 | Muito rápido para montar "equipes" de papéis | Estado durável e retomada mais fracos; muitas chamadas extras ao LLM (caro para modelo local lento) |
| AutoGen / AG2 | — | Conversa multiagente | Foco em conversa entre agentes, não em fluxo determinístico retomável; projeto em transição |
| smolagents | 1.26.0 | `CodeAgent` (o modelo escreve Python) é ótimo com modelos de código | Executar código gerado exige *sandbox*; em Windows sem Docker é arriscado |
| PydanticAI | 2.63.0 | Validação tipada excelente | Sem grafo durável equivalente ao do LangGraph |
| Próprio (do zero) | — | Controle total | Reimplementar checkpoint/retomada é caro e propenso a erros |

**Escolha: LangGraph para o fluxo de projeto + camada própria e leve para o LLM.**
O fluxo de projeto (`pesquisar → planejar → executar ⇄ revisar → finalizar`) é um `StateGraph` com `SqliteSaver`: cada nó gravado vira um ponto de retomada. Não usamos os *wrappers* de modelo do LangChain: o cliente é nosso, fala o protocolo OpenAI-compatível (que Ollama, LM Studio, llama.cpp e as APIs de nuvem falam) e cuida de JSON, novas tentativas e *fallback*.

## 3. Chamada de ferramentas com modelos pequenos

- O **LocalAgentBench** (out/2026) mostrou que, na faixa de 8 GB, o modo de ferramentas **emulado por JSON** empata ou supera o *tool calling* nativo; melhores notas: `gemma4:e4b` (94,7) e `qwen3:4b` (92,9).
- Ollama aceita **saídas estruturadas** (parâmetro `format` com JSON Schema e `response_format` na API `/v1`); a v0.34.4 passou a aplicar o esquema também a modelos "pensantes" numa passada só.
- LM Studio aceita `response_format: json_schema`, mas modelos < 7B às vezes não respeitam.

**Decisão:** modo padrão `json` (ReAct com uma ação JSON por passo, validada com Pydantic, com até 3 tentativas mostrando o erro ao modelo) e degradação automática `json_schema → json_object → texto` quando o servidor recusa. Modo `nativo` disponível na configuração.

**Pensamento ("thinking")**: Qwen3.5 e Gemma 4 pensam por padrão, o que deixa tudo várias vezes mais lento numa GPU de 8 GB. A opção `modelo.pensar: false` (padrão) envia `reasoning_effort: "none"` ao Ollama e `enable_thinking: false` ao llama.cpp. Testado de verdade com `qwen3.5:2b` no Ollama 0.40.13: com pensamento a resposta de 1 frase estourou 300 tokens só pensando; sem pensamento respondeu direto.

## 4. Modelos recomendados para 8 GB de VRAM

| Uso | Modelo (Ollama) | Tamanho | Observação |
|---|---|---|---|
| Chat/agente (padrão) | `qwen3.5:9b` | ~6,6 GB (Q4_K_M) | Novo padrão da faixa 8 GB (guia Aliteq, out/2026); cabe com 32K de contexto |
| Alternativa | `gemma4:e4b` | ~4–5 GB | Melhor nota de agente na faixa 8 GB no LocalAgentBench |
| Máquina fraca / só CPU | `qwen3.5:4b` ou `qwen3.5:2b` | 2,5–3,4 GB / ~1,3 GB | Mais rápido, raciocínio mais fraco |
| Embeddings | `qwen3-embedding:0.6b` | ~640 MB | Multilíngue (bom em português); alternativas: `embeddinggemma`, `bge-m3`, `nomic-embed-text-v2-moe` |

`nomic-embed-text` v1 é focado em inglês — evitado como padrão. `gemma4:12b` (~7,7–8 GB) não deixa folga para contexto + embeddings numa GPU de 8 GB.

## 5. RAG (biblioteca local)

| Opção | Versão | Avaliação |
|---|---|---|
| **SQLite FTS5 + vetores numpy** | stdlib + numpy 2.5.4 | Zero servidor, um arquivo, BM25 nativo; busca vetorial força-bruta é instantânea até ~100 mil trechos |
| sqlite-vec | — | Bom, mas extensão nativa pode falhar ao carregar no Python do Windows |
| LanceDB | 0.41.0 | Busca híbrida nativa; mais uma dependência binária grande |
| Chroma | 1.5.9 | Mantém o índice em RAM, não é seguro com vários processos |

**Decisão:** índice **híbrido** num único arquivo SQLite: BM25 (FTS5) + similaridade de cosseno, combinados com **Reciprocal Rank Fusion (k=60)**, consulta original + até 3 subconsultas geradas pelo modelo, no máximo 3 trechos por arquivo, *reranker* opcional (`fastembed` `TextCrossEncoder`, ex. `bge-reranker-v2-m3`). Se o modelo de embeddings não estiver disponível, a busca continua só com BM25 e os vetores são completados depois.

**Fatiamento:** texto por parágrafos com sobreposição; código por estrutura (funções/classes de nível superior via `ast` em Python, regex para outras linguagens) — a mesma ideia do *chunking* por AST do Chonkie/cAST, sem a dependência do tree-sitter. Cada trecho guarda **arquivo + local** (página do PDF, linhas do código, planilha/linhas do Excel) para a citação.

**Indexação incremental:** compara data de modificação + tamanho e, se mudou, o SHA-1; arquivos apagados saem do índice.

## 6. Pesquisa na web

- `ddgs` 9.16.1 (DuckDuckGo e outros, sem chave) com novas tentativas (0/2/5 s) para *rate limit*; alternativa SearXNG próprio.
- `trafilatura` 2.3.1 para extrair o texto principal das páginas.
- Cache em SQLite, trechos escolhidos por BM25 em relação à pergunta, cada trecho vira uma **fonte numerada** com URL.
- Ferramentas de rede são **somente leitura** (GET).

## 7. Memória de longo prazo

| Opção | Avaliação |
|---|---|
| Mem0 | Precisa de banco vetorial (Qdrant) e faz chamadas extras ao LLM a cada mensagem |
| Letta (MemGPT) | É um *runtime* completo de agentes com servidor próprio |
| **SQLite próprio** | Sessões, mensagens, resumos e "lembranças" com escopo (`global` ou `projeto:<id>`), busca híbrida, extração automática a cada 4 mensagens e ao fim de cada projeto |

## 8. Interface

| Opção | Versão | Avaliação |
|---|---|---|
| **Gradio** | 6.31.0 | `Chatbot` no formato *messages*, *streaming* com geradores, abas — feito para apps de conversa |
| Streamlit | — | Re-executa o script inteiro a cada interação; estado de chat e *streaming* de longas tarefas são mais trabalhosos |

CLI com **Typer 0.27.3 + Rich 15.0.0**.

## 9. MCP e plugins

SDK `mcp` 2.3.0 (novo `mcp.Client(StdioServerParameters)`). Ferramentas de servidores MCP aparecem como `mcp_<servidor>__<ferramenta>` e pedem confirmação por padrão. Plugins Python: arquivos `.py` numa pasta ou *entry points* `nlr.ferramentas`.

## 10. Execução de comandos e isolamento

Pesquisados: Microsoft MXC, LocalSandBox, agentbox (WSL2), llm-sandbox. Nenhum é instalação trivial no Windows. **Decisão:** política própria (área de trabalho, lista de permitidos, lista de bloqueio, confirmação, *timeout*, variáveis secretas removidas) + modo opcional `execucao: docker` (`--network none`). Ver [SEGURANCA.md](SEGURANCA.md).

## 11. Instalação no Windows

`winget install -e --id Ollama.Ollama` (ou `irm https://ollama.com/install.ps1 | iex`). LM Studio: `lms server start` e `lms load <modelo>`.

## Fontes consultadas

- LangGraph — https://github.com/langchain-ai/langgraph e https://docs.langchain.com/oss/python/langgraph/persistence
- langgraph-checkpoint-sqlite — https://pypi.org/project/langgraph-checkpoint-sqlite/
- CrewAI — https://github.com/crewAIInc/crewAI · smolagents — https://github.com/huggingface/smolagents · PydanticAI — https://ai.pydantic.dev
- Ollama: saídas estruturadas — https://docs.ollama.com/capabilities/structured-outputs ; compatibilidade OpenAI — https://docs.ollama.com/api/openai-compatibility ; Windows — https://docs.ollama.com/windows
- Biblioteca de modelos Ollama — https://ollama.com/library/qwen3.5 , https://ollama.com/library/gemma4 , https://ollama.com/library/qwen3-embedding
- LM Studio: saídas estruturadas — https://lmstudio.ai/docs/developer/openai-compat/structured-output ; CLI `lms` — https://lmstudio.ai/docs/cli
- LocalAgentBench — https://localagentbench.com
- Guia Aliteq de modelos para 8 GB — https://aliteq.com (out/2026)
- sqlite-vec — https://github.com/asg017/sqlite-vec · LanceDB — https://lancedb.github.io/lancedb/ · Chroma — https://docs.trychroma.com
- FastEmbed (reranker) — https://github.com/qdrant/fastembed · Reciprocal Rank Fusion — Cormack et al., SIGIR 2009
- Chonkie — https://github.com/chonkie-inc/chonkie · cAST (chunking por AST) — arXiv 2506.15655
- Mem0 — https://github.com/mem0ai/mem0 · Letta — https://github.com/letta-ai/letta
- ddgs — https://pypi.org/project/ddgs/ · trafilatura — https://trafilatura.readthedocs.io
- Gradio — https://www.gradio.app/docs · Streamlit — https://docs.streamlit.io
- MCP Python SDK — https://github.com/modelcontextprotocol/python-sdk
- llm-sandbox — https://github.com/vndee/llm-sandbox
