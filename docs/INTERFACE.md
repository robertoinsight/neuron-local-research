# Interface web (v0.4) / Web UI

**PT** — `nlr ui` (ou `iniciar.bat`) abre a nova interface estilo ChatGPT em http://127.0.0.1:7860. `nlr api --abrir` serve a mesma interface junto com a API. A interface antiga em Gradio continua em `nlr ui --gradio` (requer o extra `ui`).

Recursos: barra lateral de chats (novo, renomear ✎, apagar 🗑, buscar; continuações de handoff aparecem recuadas com ↳); respostas em streaming com markdown, realce de código e botões Copiar; anexar arquivo (📎) ao chat ou à biblioteca (indexação em segundo plano); seletor de modelo mostrando modelo carregado, perfil e contexto; modos Automático, Chat, Biblioteca, Web, Pesquisa profunda e Projeto; fontes numeradas abaixo de cada resposta; páginas de Projetos (progresso) e Relatórios (download); Configurações com idioma (troca toda a interface), tema claro/escuro, servidor e endereço do backend e benchmark rápido. Tema escuro por padrão, responsivo (celular), pt/en completo, sem CDN — marked, DOMPurify e highlight.js vêm embutidos em `nlr/api/static/vendor`.

**EN** — `nlr ui` (or `iniciar.bat`) opens the new ChatGPT-style UI at http://127.0.0.1:7860. `nlr api --abrir` serves it along with the API. The old Gradio UI remains at `nlr ui --gradio`. Features: chat sidebar (new/rename/delete/search, handoff chains shown with ↳), streaming markdown with code highlighting and copy buttons, file upload to chat or library, model picker (loaded model, profile, context), modes incl. deep research and project, numbered sources, projects/reports views, settings (language switches the whole UI, theme, backend URL, quick benchmark). Dark by default, responsive, no CDN at runtime.

## v0.5
- **Memória** (🧠 na lateral): fatos por escopo, com marca de origem. Dá para buscar, adicionar, editar, fixar, confirmar, apagar e esquecer os antigos. Ver `docs/MEMORIA.md`.
- **Documentos** (📚): arquivos indexados com trechos, tabelas, páginas OCR e avisos. Também mostra quais recursos estão instalados (OCR, tabelas de PDF, reranker).
- **Botão 🧠 no topo do chat:** liga o chat a um projeto (memória separada por projeto).
- **Estado do modelo:** "carregado" ou "pronto (carrega ao usar)". Atualiza após cada resposta e a cada 60 s.

## v0.6 — aba Kits (🧰)
- **Pixel Art:** solte PNG/GIF/.aseprite (vários para spritesheet ou GIF). As ações rápidas são 128→32, ½, 4× upscale, PICO-8, DB32, Endesga 32, Game Boy, 8 cores, remover fundo, extrair paleta, montar spritesheet e GIF. O modo **Personalizado** permite escolher largura, altura, fator, paleta, cores, dither e duração. O resultado aparece ampliado sem borrar, com o botão **Baixar** (os arquivos ficam em `pixel/`).
- **ABNT:** cole um DOI, ISBN ou URL por linha e clique em **Gerar referências** para ver a referência NBR 6023, a citação (Autor, ano), a forma narrativa e avisos do que faltou (⧉ copia). Na outra caixa, gere o **.docx NBR 14724** com capa, folha de rosto, sumário, seções e as referências obtidas.
- A caixa "Ativar este kit para o agente" faz as ferramentas `pixel_*` / `abnt_*` aparecerem também no chat e nos projetos. Com o kit desligado, essas ferramentas não aparecem, o que mantém o prompt curto para modelos pequenos.
- No modo **Pesquisa profunda**, há a opção **.docx ABNT**.

## v0.7 — imagens no chat (👁)
- **Anexar:** 📎 → **🖼 Imagem**, arrastar para o chat ou colar com **Ctrl+V**. Até 4 por mensagem, com miniatura removível (×).
- **Ações rápidas** acima da caixa de texto: **Analisar minuciosamente**, **Ler texto**, **Revisar pixel art**, **Pesquisar na internet pela imagem**. Também dá para escrever a pergunta e enviar normalmente.
- **🔎 Busca reversa manual:** copia a imagem para a área de transferência e abre o Google Lens, o Bing Visual Search ou o TinEye. Basta colar com Ctrl+V no site. Nada é enviado automaticamente.
- **Estado da visão** ao lado das ações: mostra o modelo de visão em uso ou um aviso com a correção (ex.: "baixe um modelo com o ícone 👁"). No seletor de modelos, os que têm visão aparecem com 👁.
- As imagens ficam em `dados/imagens/` e aparecem no histórico do chat. Durante a análise, a interface mostra as etapas (quadrantes, buscas, síntese).
- **Gradio** (`nlr ui --gradio`): aba **Imagem** com upload ou colagem, escolha da ação e pergunta.

**EN** — Attach images via 📎 → Image, drag-and-drop or Ctrl+V. Quick actions: analyze in detail, read text, review pixel art, search the web by image. 🔎 opens manual reverse search (the image is copied to the clipboard; paste it into Lens, Bing or TinEye). Vision models show 👁 in the model picker.
