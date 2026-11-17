# Neuron Local Research

Um agente de IA **autônomo, persistente e 100% local** para o seu PC: planeja e desenvolve projetos de ponta a ponta, pesquisa a fundo nos seus documentos e na internet com **citações**, lembra do que importa entre sessões e retoma trabalhos interrompidos. Roda com **Ollama, LM Studio ou llama.cpp** (GPU de 8 GB ou só CPU), com reserva opcional numa API na nuvem.

```
nlr projeto novo "Pesquise na minha biblioteca e na internet sobre X e desenvolva um script que faça Y, com testes"
```

## O que ele faz

- **Projetos de ponta a ponta**: pesquisa → plano (tarefas com critérios de aceite) → execução por sub-agentes (pesquisador, desenvolvedor, redator) → revisão (compila? testes passam? o modelo aprova?) → correção → relatório. Tudo salvo em `PLANO.md`, `DIARIO.md` e `RELATORIO.md`; **retoma** de onde parou.
- **RAG na sua biblioteca**: PDF, Word, Excel, CSV, Markdown, texto e código; indexação incremental; busca híbrida (palavras-chave + semântica); respostas citando arquivo e página/linhas.
- **Pesquisa na web** com leitura das páginas e citações, **cruzada** com a biblioteca (seção "Biblioteca × Web").
- **Memória de longo prazo**: fatos, preferências e decisões, globais ou por projeto.
- **Ferramentas extensíveis**: arquivos, comandos (com confirmação), Python, web, memória, **plugins** em Python e servidores **MCP**.
- **CLI** (terminal) e **interface web** (Gradio) em português.
- **Seguro por padrão**: escreve só na pasta do projeto, todo comando pede confirmação, lista de bloqueio de comandos perigosos, *timeouts*, segredos no `.env`.

## Novidades da versão 0.7 (fase 5: visão)
- **Imagens no chat:** anexe pelo 📎 → 🖼 Imagem, arraste ou cole com **Ctrl+V**. A miniatura aparece com as ações rápidas **Analisar minuciosamente**, **Ler texto**, **Revisar pixel art** e **Pesquisar na internet pela imagem**. Também na aba Imagem do Gradio.
- **Terminal:** `nlr imagem analisar FOTO [--modo minucioso|geral|texto|pixel] [--pergunta ...]`, `nlr imagem pesquisar FOTO [--foco ...]` e `nlr imagem status`.
- **Detecção de visão:** avisa se o modelo escolhido não tem visão (ícone 👁 no LM Studio) ou não está carregado e explica como corrigir. Se `modelo_visao` estiver vazio, usa o modelo de chat quando ele tem visão.
- **Análise minuciosa em etapas** (quadrantes ampliados + síntese), OCR, revisão de pixel art com medidas objetivas e pesquisa web a partir da imagem, com fontes numeradas.
- **Busca reversa:** manual (Google Lens, Bing, TinEye, sem enviar nada automaticamente) ou automática pela SerpApi, desligada por padrão e só com consentimento e chave. Sem reconhecimento facial.
- API: `/api/imagens`, `/api/visao`, `/api/imagem/analisar`, `/api/imagem/pesquisar`. Pillow agora é dependência padrão. Ver `docs/VISAO.md`.

## Novidades da versão 0.6 (fase 4)
- **Kit Pixel Art** (opcional, `pip install -e ".[pixel]"` ou `instalar.ps1 -ComPixel`): redimensionar sem borrar (128→32), paletas PICO-8/DB32/Endesga/Game Boy, remover fundo, spritesheets + JSON, GIF e integração com o **Aseprite** (`--batch`, scripts Lua). Ver `docs/KIT-PIXEL.md`.
- **Kit ABNT** (opcional, `".[abnt]"` ou `-ComABNT`): referências NBR 6023 a partir de DOI, ISBN ou URL, citações NBR 10520 e documento `.docx` NBR 14724. A pesquisa profunda também gera o relatório em ABNT. Ver `docs/KIT-ABNT.md`.
- **Aba Kits** na interface (ações rápidas), comandos `nlr pixel …`, `nlr abnt …` e `nlr kits --ativar pixel`.

## Novidades da versão 0.5 (fase 3)
- **Correção:** o cabeçalho não mostra mais "não carregado" com o modelo respondendo. Agora indica "carregado" ou "pronto (carrega ao usar)" e se atualiza após cada resposta.
- **Documentos difíceis:** PDFs escaneados com OCR opcional (`pip install -e ".[documentos]"`). As tabelas de PDF/DOCX/XLSX viram markdown, e as páginas escaneadas são detectadas sozinhas. Ver `docs/DOCUMENTOS.md`.
- **RAG melhorado:** busca híbrida BM25 + embeddings, reranker leve por padrão, trechos por título/tabela e citações com página, seção e tabela.
- **Memória por projeto:** cada fato é marcado como literal do usuário, inferido ou ⚠ inhearsay. Há deduplicação e esquecimento, e as páginas **Memória** e **Documentos** foram adicionadas à interface. Ver `docs/MEMORIA.md`.
- **Inglês:** `nlr --idioma en --help` e a interface Gradio (`nlr ui --gradio`).

## Novidades da versão 0.4 (fase 2)
- **Nova interface web estilo ChatGPT** (`nlr ui` / `iniciar.bat`): chats na lateral, streaming, markdown e código, anexos, seletor de modelo, modos (incl. pesquisa profunda e projeto), fontes, tema escuro/claro, pt/en. Ver `docs/INTERFACE.md`. Gradio antigo: `nlr ui --gradio`.
- **Pesquisa profunda**: `nlr pesquisar "..." --profunda` — relatório longo com citações verificadas (md/docx/pdf). Ver `docs/PESQUISA-PROFUNDA.md`.
- **`nlr benchmark`**: velocidade, JSON, ferramentas e recomendação de perfil. Ver `docs/BENCHMARK.md`.
- **Instalador Windows (.exe)**: script Inno Setup em `instalador/` + workflow `.github/workflows/instalador-windows.yml` que gera o .exe. O caminho `.bat` continua.
- **Guarda inhearsay** no handoff de chats.

## Novidades da versão 0.3 (fase 1 do NLR)

- **Novo nome**: Neuron Local Research (NLR). Comando `nlr` (o antigo `agente` continua funcionando).
- **Português e inglês**: `idioma: pt|en` no config.yaml, `nlr --idioma en ...` ou `NLR_IDIOMA=en`.
- **Qualquer modelo, de qualquer tamanho**: detecta RAM/GPU/VRAM, o modelo **carregado** e o **contexto real** do servidor
  (LM Studio, Ollama, llama.cpp) e escolhe um perfil (pequeno, médio, grande) que ajusta ferramentas, passos e orçamento.
- **`modelo_chat: auto` corrigido**: usa o modelo carregado; se nenhum estiver carregado, escolhe o maior que cabe no PC e avisa.
  O modelo de embeddings também é detectado sozinho.
- **Ferramentas mais confiáveis**: roteador (o modelo vê só as ferramentas relevantes), erros que dizem como corrigir
  (com exemplo JSON), correção automática de nome de ferramenta digitado errado e **anti-loop**.
- **Novo chat automático**: perto de 80% do contexto, o NLR resume o estado salvo e continua num chat novo ligado ao anterior.
- **API HTTP** (`nlr api`), base da futura interface estilo ChatGPT.

## Começo rápido (Windows + LM Studio)

1. No LM Studio: baixe e **carregue** um modelo de chat; na aba **Developer**, clique em **Start Server**.
2. Descompacte o NLR numa pasta simples (ex.: `C:\IA\neuron-local-research`) e dê dois cliques em **`instalar.bat`**.
   Não precisa ter Python: o instalador baixa o `uv` e um Python 3.12 só para o NLR.
3. Confira: `iniciar.bat modelos` (mostra o modelo carregado, o contexto e o perfil).
4. Use: `iniciar.bat chat` (terminal) ou `iniciar.bat` (interface web em http://127.0.0.1:7860).

Passo a passo com imagens em texto: [docs/LM-STUDIO.md](docs/LM-STUDIO.md). Ollama/llama.cpp/Linux: [docs/INSTALACAO.md](docs/INSTALACAO.md).
English: [README.en.md](README.en.md).

## Comandos principais

| Comando | Para quê |
|---|---|
| `nlr chat` | Conversa com roteamento automático (`/web`, `/biblioteca`, `/ambos`, `/agente`, `/projeto`, `/lembrar`) |
| `nlr perguntar "..." --modo ambos` | Uma pergunta, uma resposta com fontes |
| `nlr pesquisar "..." --fontes ambos --salvar rel.md` | Pesquisa profunda com relatório |
| `nlr projeto novo "objetivo" [--autonomo]` | Cria e executa um projeto |
| `nlr projeto retomar <id>` / `continuar <id> "pedido"` / `listar` / `status <id>` | Gerencia projetos |
| `nlr indexar` · `nlr biblioteca ...` | Biblioteca |
| `nlr memoria listar/adicionar/buscar/esquecer` | Memória |
| `nlr doctor` | Diagnóstico (hardware, servidor, modelo carregado, contexto real, perfil) |
| `nlr modelos` · `nlr hardware` | Modelos do servidor e perfil escolhido · RAM/GPU/VRAM e tamanho recomendado |
| `nlr api` | API HTTP em http://127.0.0.1:8765 (docs em /docs) |
| `nlr --idioma en ...` | Qualquer comando em inglês |
| `nlr ui` | Interface web |

## Documentação

- [docs/LM-STUDIO.md](docs/LM-STUDIO.md) — **passo a passo simples com o LM Studio**
- [docs/MODELOS-E-PERFIS.md](docs/MODELOS-E-PERFIS.md) — detecção automática, perfis, roteador, anti-loop, novo chat automático
- [docs/DOCUMENTOS.md](docs/DOCUMENTOS.md) — OCR, tabelas, busca híbrida, reranker e chunking (v0.5)
- [docs/VISAO.md](docs/VISAO.md) — **imagens: modelos de visão para 8 GB, análise, OCR, pesquisa pela imagem (v0.7)**
- [docs/MEMORIA.md](docs/MEMORIA.md) — memória por projeto, marcas de origem, esquecimento (v0.5)
- [docs/INTERFACE.md](docs/INTERFACE.md) · [docs/PESQUISA-PROFUNDA.md](docs/PESQUISA-PROFUNDA.md) · [docs/BENCHMARK.md](docs/BENCHMARK.md)
- [docs/API.md](docs/API.md) — API HTTP (base da interface estilo ChatGPT)
- [docs/ROTEIRO.md](docs/ROTEIRO.md) — o que foi feito nas fases 1–5 e o que vem depois
- [docs/INSTALACAO.md](docs/INSTALACAO.md) — instalação (Windows, LM Studio, Linux), modelos para 8 GB
- [docs/BIBLIOTECA.md](docs/BIBLIOTECA.md) — configurar e indexar seus documentos
- [docs/USO.md](docs/USO.md) — exemplos reais, incluindo "pesquise na minha biblioteca e na internet e desenvolva um projeto"
- [docs/ARQUITETURA.md](docs/ARQUITETURA.md) — como funciona por dentro (diagramas)
- [docs/PESQUISA.md](docs/PESQUISA.md) — por que LangGraph, SQLite, Gradio, Qwen3.5… (com fontes)
- [docs/ESTENDER.md](docs/ESTENDER.md) — plugins, MCP, backends, novos agentes
- [docs/SEGURANCA.md](docs/SEGURANCA.md) — permissões, modo autônomo e limites
- [docs/SOLUCAO-DE-PROBLEMAS.md](docs/SOLUCAO-DE-PROBLEMAS.md)

## Estrutura

```
neuron-local-research/
├── nlr/                   código
│   ├── nucleo/            hardware, descoberta de modelos, perfis, roteador, anti-loop, handoff
│   ├── i18n/              textos em português e inglês
│   ├── api/               API HTTP (FastAPI)
│   └── agentes/ biblioteca/ web/ memoria/ ferramentas/ llm/ ui/ cli.py
├── plugins/               suas ferramentas extras (.py)
├── tests/                 testes automáticos (servidor de modelo falso + amostras)
├── docs/                  documentação
├── instalar.bat/.ps1/.sh  instaladores
├── iniciar.bat/.ps1/.sh   atalhos para rodar
├── config.exemplo.yaml    configuração comentada (o instalador cria o config.yaml)
└── .env.exemplo           modelo do arquivo de segredos
```

Licença MIT.
