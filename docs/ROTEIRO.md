# Roteiro do Neuron Local Research

## Fase 1 — v0.3 (esta versão)
- [x] Novo nome (NLR), comando `nlr` (alias `agente`)
- [x] Português (padrão) e inglês: CLI, mensagens de erro do agente, prompts
- [x] Detecção de hardware (RAM, GPU NVIDIA, VRAM; Apple Silicon)
- [x] Descoberta de modelos e contexto real (LM Studio, Ollama, llama.cpp, OpenAI-compatível); `auto` corrigido
- [x] Perfis pequeno/médio/grande
- [x] Roteador de ferramentas, erros com exemplo, correção de nome, anti-loop
- [x] Novo chat automático (handoff) aos 80% do contexto
- [x] API HTTP (FastAPI + SSE) para a nova interface
- [x] Instalador de 1 clique com uv (baixa o Python sozinho)

## Fase 2
- [ ] Interface própria estilo ChatGPT (barra lateral de chats, streaming, fontes, troca de idioma, tema escuro)
- [ ] Instalador `.exe`
- [ ] Pesquisa web profunda em várias rodadas (perguntas derivadas, leitura de mais páginas, checagem cruzada)
- [x] RAG melhorado (tabelas, PDFs escaneados com OCR, reranker por padrão quando couber) — feito na v0.5

## Fase 3
- [x] Kit de pixel art (paletas, spritesheets, Aseprite) — feito na v0.6 (revisão por modelo de visão: ainda não)
- [x] Modo ABNT (referências conferidas por DOI/ISBN/URL) — feito na v0.6
- [x] `nlr benchmark` (testa modelos no seu PC e recomenda) — feito na v0.4

## Inglês
Desde a v0.5 o `--help` da CLI (`nlr --idioma en --help`, ou `NLR_IDIOMA=en`) e a interface Gradio antiga
também estão em inglês. Ainda em português: parte das mensagens de progresso/erro da CLI antiga.

## Fase 2 — concluída (v0.4.0)
- [x] Interface web própria estilo ChatGPT (FastAPI, sem CDN), padrão no lugar do Gradio
- [x] Pesquisa profunda (rodadas, lacunas/contradições, citações verificadas, md/docx/pdf)
- [x] `nlr benchmark`
- [x] Instalador Windows (.iss Inno Setup + workflow GitHub Actions) — .exe não compilado/testado ainda
- [x] Guarda inhearsay no handoff

## Fase 3 — concluída (v0.5.0)
- [x] Correção: cabeçalho mostrava "não carregado" com o modelo respondendo (lista de modelos ficava em cache desde a 1ª conexão)
- [x] Documentos difíceis: detecção de página escaneada, OCR opcional (rapidocr → tesseract → aviso), tabelas de PDF/DOCX/XLSX em markdown
- [x] RAG: busca híbrida com peso, reranker leve padrão, chunking por títulos/tabelas, citação com página/seção/tabela/OCR
- [x] Memória de longo prazo por projeto, com marca de origem (literal/inferido/inhearsay), deduplicação, esquecimento e página na UI
- [x] i18n: `--help` da CLI e interface Gradio em inglês

## Fase 4 — concluída (v0.6.0)
- [x] Kit Pixel Art opcional (Pillow): nearest-neighbor, paletas (PICO-8, DB16/DB32, Endesga 32, Game Boy, .gpl/.hex/.pal), reduzir/extrair/aplicar, remover fundo, montar/fatiar spritesheet + JSON (formato Aseprite), upscale inteiro, prévia e GIF
- [x] Aseprite CLI (`--batch`, detecção no Windows/Steam/itch, exportar png/sheet+json, scripts Lua) com leitor .aseprite embutido quando o Aseprite não está instalado
- [x] Kit ABNT: NBR 6023 por DOI (Crossref), ISBN (OpenLibrary/Google Books), URL e arquivos da biblioteca; NBR 10520 autor-data (2023 e 2002); .docx NBR 14724
- [x] Pesquisa profunda → relatório `-abnt.docx`; aba **Kits** na interface; `nlr pixel`, `nlr abnt`, `nlr kits`; instaladores `-ComPixel` / `-ComABNT`

## Fase 5 — concluída (v0.7.0)
- [x] `analisar_imagem`: análise minuciosa com modelo de visão (visão geral + quadrantes ampliados, EXIF, modos geral/minucioso/texto/pixel)
- [x] `pesquisar_por_imagem`: identifica o conteúdo da imagem e pesquisa na web com fontes citáveis
- [x] `modelo.modelo_visao` no config.yaml
- [x] Anexar imagens na interface de chat (📎, arrastar, Ctrl+V) com miniatura e ações rápidas; aba Imagem no Gradio
- [x] CLI `nlr imagem analisar|pesquisar|status` (ajuda pt/en)
- [x] Rotas `/api/imagens`, `/api/visao`, `/api/imagem/analisar`, `/api/imagem/pesquisar`
- [x] Detecção de visão (LM Studio `vlm`, Ollama `capabilities`, llama.cpp `/props`) com aviso e correção; modelo de chat usado se tiver visão
- [x] Minucioso em etapas, anti-loop, revisão de pixel art com medidas objetivas
- [x] Busca reversa: manual (Lens/Bing/TinEye) e SerpApi opcional (desligada, exige consentimento + chave, bloqueada com pessoas)
- [x] Teste real em CPU com Qwen2.5-VL 3B (ver `docs/VISAO.md`)
- [ ] Testar no Windows + LM Studio + GPU com modelos 7B

## Próximas ideias
- [ ] Geração de paletas por descrição; revisão de sprites mais confiável (exige modelo 7B+)
- [ ] Análise de várias imagens comparadas (antes/depois, quadros de animação) e imagens dentro de PDFs
- [ ] ABNT: apêndices/anexos, listas de figuras e tabelas, resumo em língua estrangeira; exportar PDF/A
- [ ] Tabelas de PDF sem pdfplumber (heurística por colunas) e OCR de imagens soltas (PNG/JPG) na biblioteca
- [ ] Mensagens de progresso restantes da CLI em inglês
