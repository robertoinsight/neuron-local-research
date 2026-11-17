# Neuron Local Research (NLR)

An **autonomous, persistent, 100% local** AI research and project agent for your own PC. It plans and builds projects,
researches your documents (RAG) and the web with **citations**, remembers what matters, and resumes interrupted work.
Works with **LM Studio, Ollama, llama.cpp** or any OpenAI-compatible API. Default language: Portuguese — switch to English
with `idioma: en` in `config.yaml`, `nlr --idioma en ...` or `NLR_IDIOMA=en`.


## What's new in 0.7 (phase 5: vision)
- **Images in chat:** attach with 📎 → 🖼 Image, drag-and-drop or **Ctrl+V** paste. A thumbnail appears with the quick actions **Analyze in detail**, **Read text**, **Review pixel art** and **Search the web by image**. A Gradio "Image" tab is included too.
- **CLI:** `nlr imagem analisar PHOTO [--modo minucioso|geral|texto|pixel] [--pergunta ...]`, `nlr imagem pesquisar PHOTO [--foco ...]`, `nlr imagem status`.
- **Vision detection:** warns when the chosen model has no vision (the 👁 icon in LM Studio) or is not loaded, with a fix. With an empty `modelo_visao`, the chat model is used if it supports vision.
- Staged detailed analysis (zoomed quadrants + synthesis), OCR, pixel-art review grounded on measurements, and web search driven by the image, with numbered sources.
- **Reverse image search:** manual (Google Lens / Bing / TinEye) or automatic via SerpApi. The automatic one is off by default and needs explicit consent plus an API key. No facial recognition.
- API: `/api/imagens`, `/api/visao`, `/api/imagem/analisar`, `/api/imagem/pesquisar`. Pillow is now a core dependency. See `docs/VISAO.md` (pt-BR).

## What's new in 0.6 (phase 4)
- **Pixel Art kit** (optional, `pip install -e ".[pixel]"` or `instalar.ps1 -ComPixel`): crisp nearest-neighbor resize, PICO-8/DB32/Endesga/Game Boy palettes, background removal, spritesheets + JSON, GIFs and **Aseprite** CLI integration. See `docs/KIT-PIXEL.md` (pt-BR).
- **ABNT kit** (Brazilian academic standards; `".[abnt]"` or `-ComABNT`): NBR 6023 references from DOI/ISBN/URL, NBR 10520 citations and NBR 14724 `.docx`. Deep research can output an ABNT report. See `docs/KIT-ABNT.md`.
- **Kits tab** in the UI, `nlr pixel …`, `nlr abnt …`, `nlr kits --ativar pixel`.

## What's new in 0.5 (phase 3)
- **Fix:** the header no longer says "not loaded" while the model is answering. It now shows "loaded" or "ready (loads on use)" and refreshes after each answer.
- **Hard documents:** scanned PDFs with optional OCR (`pip install -e ".[documentos]"`). PDF/DOCX/XLSX tables become markdown, and scanned pages are detected automatically. See `docs/DOCUMENTOS.md` (pt-BR).
- **Better RAG:** hybrid BM25 + embeddings search, light reranker by default, chunks by heading/table, and citations with page, section and table.
- **Per-project memory:** each fact is tagged user-literal, inferred or ⚠ inhearsay. Memories are deduplicated and old ones forgotten, and **Memory** and **Documents** pages were added to the UI. See `docs/MEMORIA.md` (pt-BR).
- **English:** `nlr --idioma en --help` and the Gradio UI (`nlr ui --gradio`).

## What's new in 0.4 (phase 2)
- **New ChatGPT-style web UI** (`nlr ui` / `iniciar.bat`) — see `docs/INTERFACE.md`; old Gradio UI via `nlr ui --gradio`.
- **Deep research**: `nlr pesquisar "..." --profunda` — long report with verified citations (md/docx/pdf). See `docs/PESQUISA-PROFUNDA.md`.
- **`nlr benchmark`** — see `docs/BENCHMARK.md`.
- **Windows installer (.exe)**: Inno Setup script in `instalador/` + GitHub Actions workflow that builds it. The `.bat` path remains.
- **Inhearsay guard** on chat handoff.

## What's new in 0.3 (phase 1)
- Works with **any model size**: detects RAM/GPU/VRAM, the **loaded** model and the **real context length** from the server,
  then picks a profile (small/medium/large) that tunes tools, steps and token budget.
- `modelo_chat: auto` uses the loaded model; if none is loaded it picks the largest one that fits and tells you.
  Embedding model detected automatically.
- More reliable tools for small models: tool router, corrective errors with a JSON example, typo auto-fix, anti-loop guard.
- **Automatic chat handoff**: at ~80% of the context, NLR summarizes the saved state and continues in a new linked chat.
- HTTP API (`nlr api`, FastAPI + SSE), the base for the upcoming ChatGPT-style UI.
- One-click Windows installer using `uv` (downloads its own Python).

## Quick start (Windows + LM Studio)
1. In LM Studio, load a chat model and click **Developer → Start Server** (port 1234).
2. Unzip NLR to a simple path (e.g. `C:\IA\neuron-local-research`) and double-click **`instalar.bat`** (choose 2 = English).
3. Check: `iniciar.bat modelos`.
4. Use: `iniciar.bat --idioma en chat` or `iniciar.bat` (web UI at http://127.0.0.1:7860).

Linux/macOS: `./instalar.sh --backend lmstudio` then `./iniciar.sh`.

## Main commands
`nlr chat` · `nlr perguntar "..." --modo ambos` (ask) · `nlr pesquisar "..." --fontes ambos` (research) ·
`nlr projeto novo "goal"` (project) · `nlr biblioteca adicionar <folder>` + `nlr indexar` (library) ·
`nlr modelos` · `nlr hardware` · `nlr doctor` · `nlr api` · `nlr ui`

Command names are in Portuguese for now; detailed docs are in `docs/` (Portuguese). License: MIT.

## Status / limitations
Tested on Linux with Ollama on CPU (Qwen2.5 0.5B and 1.5B) and with simulated LM Studio responses. Not yet tested on
Windows, with a real LM Studio, or on GPU. Very small models (≤ 2B) still fail on multi-step tasks more often.
