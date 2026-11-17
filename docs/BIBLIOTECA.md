# Biblioteca (seus documentos)

A biblioteca é o conjunto de pastas que o agente indexa para responder com **citações** ("contrato.docx", "manual.pdf, p. 2", "vendas.xlsx, planilha Vendas, linhas 2-40", "motor.py, linhas 10-55").

## Configurar

```bash
nlr biblioteca adicionar "C:/Users/SeuNome/Documents/Biblioteca"    # pode repetir com várias pastas
nlr biblioteca adicionar "D:/Projetos/codigo"
nlr indexar                       # primeira vez: lê tudo
nlr biblioteca status             # arquivos, trechos, vetores, erros
nlr biblioteca buscar "multa rescisão"   # testa a busca SEM usar o modelo
nlr biblioteca remover "D:/Projetos/codigo"
```

Ou edite o `config.yaml` (os comentários são preservados quando a CLI altera as pastas):

```yaml
biblioteca:
  pastas:
    - "C:/Users/SeuNome/Documents/Biblioteca"
  tamanho_trecho: 1200     # caracteres por trecho (menor = citações mais precisas; maior = mais contexto)
  sobreposicao: 200
  max_arquivo_mb: 50       # arquivos maiores são ignorados
  embeddings: backend      # backend (vetores pelo Ollama/LM Studio) | nenhum (só palavras-chave)
  reranker: leve           # leve (padrão v0.5, sem dependências) | fastembed (cross-encoder, pip install fastembed) | nenhum
  ocr: auto                # auto | rapidocr | tesseract | nenhum  (PDF escaneado; ver docs/DOCUMENTOS.md)
  tabelas_pdf: true        # tabelas de PDF em markdown (precisa do pdfplumber)
  k: 8                     # trechos entregues ao modelo por pergunta
```

Na interface web: aba **Biblioteca** (adicionar pasta, indexar, buscar).

## Formatos suportados

| Tipo | Extensões | Como é citado |
|---|---|---|
| PDF (com texto) | `.pdf` | `arquivo.pdf, p. 3` |
| Word | `.docx` (inclui tabelas) | `arquivo.docx` |
| Planilhas | `.xlsx`, `.xlsm`, `.csv`, `.tsv` (detecta `;` e `,`) | `planilha Vendas, linhas 2-40` |
| Texto | `.txt`, `.md`, `.rst`, `.json`, `.html`, `.yaml`, `.toml`, `.ini` (detecta UTF-8/Windows-1252) | `arquivo.md` |
| Código | `.py`, `.js`, `.ts`, `.java`, `.c/.cpp`, `.cs`, `.go`, `.rs`, `.rb`, `.php`, `.lua`, `.gd`, `.sh`, `.ps1`, `.sql`… | `motor.py, linhas 10-55` |

Ignorados por padrão: `.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`, `*.min.js` (lista em `biblioteca.ignorar`). PDFs escaneados (só imagem) não têm texto: passe um OCR antes (ex.: `ocrmypdf`).

## Como funciona

> v0.5: trechos por título/tabela, tabelas em markdown, OCR e reranker leve. Detalhes em [DOCUMENTOS.md](DOCUMENTOS.md).


1. **Indexação incremental**: `nlr indexar` compara data/tamanho (e o SHA-1 quando mudam) de cada arquivo. Só o que mudou é reprocessado; arquivos apagados saem do índice. Use `--forcar` para refazer tudo e `--pasta X` para indexar só uma pasta.
2. **Fatiamento**: texto em trechos com sobreposição; código por funções/classes; planilhas em blocos de linhas no formato `coluna: valor`.
3. **Busca híbrida**: palavras-chave (BM25 do SQLite FTS5) + similaridade semântica (embeddings), unidas por *Reciprocal Rank Fusion*. A pergunta é expandida em até 3 subconsultas pelo modelo. No máximo 3 trechos por arquivo, para variar as fontes.
4. **Resposta**: os trechos viram fontes numeradas `[1]`, `[2]`…; o modelo é instruído a citar cada afirmação e a dizer quando as fontes não cobrem algo. Citações inválidas (números que não existem) geram aviso.

Tudo fica em `dados/biblioteca.db` (um arquivo SQLite). Apagar esse arquivo e rodar `nlr indexar` reconstrói o índice.

## Trocar o modelo de embeddings

Se você mudar `modelo.modelo_embeddings`, o índice percebe e recalcula os vetores no próximo `nlr indexar` (o texto não é relido). Sem servidor de embeddings, a indexação continua só com palavras-chave e `nlr indexar --vetores` completa os vetores depois.

## Dicas para bibliotecas grandes

- Até ~100 mil trechos a busca vetorial em memória é instantânea. Acima disso, divida em várias configurações (`agente -c outra.yaml ...`).
- A primeira indexação de muitos PDFs leva tempo por causa dos embeddings (~50–200 trechos/s em GPU; bem menos em CPU). Pode interromper: o que já foi feito fica salvo.
- `biblioteca.embeddings: nenhum` deixa a indexação muito mais rápida (só palavras-chave).
