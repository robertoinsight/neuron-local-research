# Documentos difíceis e RAG (v0.5)

## OCR de PDFs escaneados (opcional)
O NLR detecta sozinho as páginas escaneadas: página com imagem e quase sem texto extraível (< 40 letras/dígitos).
Nessas páginas ele tenta OCR, nesta ordem:

1. **rapidocr-onnxruntime**: só pip, sem programa externo, funciona no Windows, em CPU.
2. **tesseract**: precisa do `pytesseract` e do programa `tesseract` no PATH. O idioma vem de `biblioteca.ocr_idiomas`, padrão `por+eng`.
3. **Sem OCR**: a página é pulada e aparece um aviso em `nlr biblioteca documentos` e na página **Documentos** da interface.

Para gerar a imagem da página ele usa o `pypdfium2`, se estiver instalado. Sem ele, usa as imagens embutidas no PDF (via pypdf), o que já cobre a maioria dos escaneados (uma imagem por página).
Os trechos lidos por OCR são citados como `p. 3 (OCR)`.

Instalação: `pip install -e ".[documentos]"`, ou `instalar.ps1 -ComDocumentos` / `instalar.sh --com-documentos`.
São cerca de 150 MB a mais (onnxruntime + opencv).
Config: `biblioteca.ocr: auto | rapidocr | tesseract | nenhum`.

## Tabelas → markdown
- **DOCX:** o documento é lido na ordem (parágrafos, títulos e tabelas). Cada tabela vira um trecho markdown citado como `tabela 2 (seção Preços)`. Células mescladas não são repetidas.
- **XLSX/CSV:** blocos markdown com o cabeçalho repetido em cada bloco, citados como `planilha Vendas, linhas 2-40`.
- **PDF:** usa o `pdfplumber` (extra `documentos`, ou `biblioteca.tabelas_pdf: false` para desligar), citado como `p. 4, tabela 1`. Sem ele, o texto da tabela entra como texto comum.

## RAG melhorado
- **Busca híbrida:** BM25 (SQLite FTS5) + embeddings, fundidos por RRF. O peso dos vetores fica em `biblioteca.peso_vetor`. Sem modelo de embeddings, a busca usa só BM25.
- **Reranking leve** (`biblioteca.reranker: leve`, o novo padrão), sem dependências. A nota leva em conta:
  - a cobertura dos termos da pergunta (sem acento, por radical);
  - a proximidade entre termos vizinhos;
  - números exatos;
  - o título da seção.
  A nota é combinada com a fusão. Para máquinas melhores há `fastembed`, um cross-encoder ONNX (extra `reranker`). Se ele falhar, o NLR volta para o leve.
- **Chunking por estrutura:** o texto é dividido por títulos (markdown `#` ou numerados `3.2 Título`). Cada trecho leva o título da seção no texto (`[Garantia]`) e na citação (`p. 4 · §Garantia`). Tabelas markdown nunca são cortadas no meio; quando grandes, cada bloco repete o cabeçalho. Título sozinho não vira trecho.
- **Citações com página:** PDFs já citavam `p. N`; agora a citação também traz seção, tabela e OCR.

Depois de atualizar, reindexe para aplicar o novo fatiamento: `nlr indexar --forcar`.

## Teste real (qwen2.5:1.5b, CPU)
Biblioteca com um PDF escaneado (imagem), um DOCX com tabela e um PDF com tabela.
- Pergunta: "Qual o total do orçamento do Erebos e quanto custa a arte?"
- Resposta correta: R$ 18.400 (lido por OCR) e R$ 9.500 (da tabela do PDF).
- As fontes saíram citadas como `orcamento-escaneado.pdf, p. 1 (OCR)` e `custos.pdf, p. 1, tabela 1`.
