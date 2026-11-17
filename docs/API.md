# API HTTP do NLR

`nlr api` (ou `iniciar.bat api`) inicia a API em http://127.0.0.1:8765. Documentação interativa em `/docs`.
Ela será usada pela interface estilo ChatGPT (fase 2), mas já pode ser usada por outros programas.

| Método | Rota | Para quê |
|---|---|---|
| GET | `/api/saude` | versão, idioma, servidor de modelos no ar |
| GET | `/api/modelos` | modelos, carregado, contexto real, perfil, hardware |
| GET | `/api/config` | idioma, modos, handoff |
| PUT | `/api/idioma` | `{"idioma": "en"}` |
| GET | `/api/chats` | lista de chats (com `pai` quando houve novo chat automático) |
| POST | `/api/chats` | cria um chat → `{"id": ...}` |
| GET | `/api/chats/{id}` | mensagens, `cadeia` (chats ligados) e `continuacao` |
| POST | `/api/chats/{id}/mensagens` | `{"texto": "...", "modo": "auto", "stream": true}` |

Com `stream: true`, a resposta é Server-Sent Events:

```
event: evento   data: {"tipo": "rota", "msg": "conversa"}
event: token    data: {"t": "Ol"}
event: handoff  data: {"tipo": "handoff", "msg": "O chat chegou a 80%..."}
event: fim      data: {"texto": "...", "rota": "...", "sessao": "<id do chat atual>", "avisos": [], "fontes": []}
```

Se houve novo chat automático, `sessao` traz o id do chat novo: a interface deve passar a usá-lo.

Segurança: a API não tem senha e escuta só em 127.0.0.1. Não a exponha na rede.

## Rotas novas na v0.4 / New routes

| Método | Rota | Descrição |
|---|---|---|
| GET | `/` | Interface web |
| GET | `/api/i18n/{pt\|en}` | Textos da interface |
| GET/PUT | `/api/configuracoes` | Ler/salvar idioma, tema, backend (grava config.yaml) |
| GET / PUT | `/api/modelos`, `/api/modelo` | Listar / trocar modelo |
| GET/POST | `/api/chats?q=` | Listar (com busca) / criar chat |
| GET/PATCH/DELETE | `/api/chats/{id}` | Ler / renomear / apagar |
| POST | `/api/chats/{id}/mensagens` | Enviar mensagem (SSE; `modo`, `anexos`) |
| POST | `/api/upload` | Upload base64 (`destino`: chat ou biblioteca) |
| POST | `/api/pesquisa` | Pesquisa profunda (job) |
| GET | `/api/relatorios`, `/api/relatorios/{nome}` | Listar / baixar relatórios |
| GET/POST | `/api/projetos`, `/api/projetos/{id}` | Projetos e progresso |
| POST/GET | `/api/benchmark`, `/api/benchmarks` | Rodar / histórico |
| GET | `/api/jobs/{id}` | Status e progresso de jobs |

## Rotas novas na v0.5
| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/memoria?escopo=&q=` | Lista fatos (com marca, usos, evidência) e escopos |
| POST | `/api/memoria` | `{"texto", "escopo", "tipo"}`: fato literal do usuário |
| PATCH | `/api/memoria/{id}` | `{"texto", "escopo", "tipo", "marca", "fixada"}` |
| DELETE | `/api/memoria/{id}` | Apaga |
| POST | `/api/memoria/esquecer?escopo=` | Esquecimento (inferidos antigos + excesso) |
| PATCH | `/api/chats/{id}` | agora aceita `{"projeto": "nome"}` (escopo da memória) |
| GET | `/api/documentos` | Arquivos indexados (trechos, tabelas, páginas OCR, avisos) + recursos disponíveis |
| GET | `/api/modelos` | agora relê o estado do servidor a cada chamada e inclui `ultima_resposta` |

## Rotas novas na v0.6 (kits)
| Método | Rota | O que faz |
|---|---|---|
| GET | `/api/kits` | Estado dos kits, Aseprite detectado, paletas embutidas |
| PUT | `/api/kits` | `{"pixel": true, "abnt": false, "aseprite": "C:/…/Aseprite.exe", "salvar": true}` liga/desliga (e grava no `config.yaml`) |
| POST | `/api/pixel` | `{"acao": "redimensionar", "imagens_b64": ["…"], "largura": 32}`. Ações: redimensionar, upscale, aplicar_paleta, reduzir_paleta, extrair_paleta, remover_fundo, preview, montar, fatiar, gif, aseprite_sheet. Devolve `arquivo`, `url`, `imagem_b64` (prévia), `tamanho`, `paleta`/`json` quando houver |
| GET | `/api/kits/arquivo/{pixel\|abnt}/{nome}` | Baixa um arquivo gerado |
| POST | `/api/abnt/referencias` | `{"identificadores": ["10.1038/nature14539", "9788535914849", "https://…"]}` → referências NBR 6023 + citações |
| POST | `/api/abnt/documento` | `{"titulo", "autor", "instituicao", "local", "ano", "natureza", "texto" (markdown), "referencias" ou "referencias_prontas"}` → `.docx` NBR 14724 |
| POST | `/api/pesquisa` | novo campo `"abnt": true` gera também `relatorio-abnt.docx` |

## Rotas novas na v0.7 (visão)
| Método | Rota | O que faz |
|---|---|---|
| POST | `/api/imagens` | `{"nome": "foto.png", "dados_b64": "…"}` → `{"id", "nome", "largura", "altura", "url", "miniatura"}` (valida com Pillow, até 25 MB) |
| GET | `/api/imagens/{id}` | Devolve a imagem salva |
| GET | `/api/visao` | Estado: `ok`, `modelo`, `origem` (modelo_visao/modelo_chat/auto), `tem_visao`, `carregado`, `backend`, `avisos`, `erro`, `modelos_visao`, `modo_padrao`, `busca_reversa` (`provedor`, `consentimento_envio`, `chave_presente`, `ativa`) |
| POST | `/api/imagem/analisar` | `{"imagem": "<id>" ou "imagens": [...], "modo": "minucioso\|geral\|texto\|pixel", "pergunta": "", "job": false}` → `{"texto", "info", "modo", "modelo", "vistas", "avisos"}`; com `"job": true` devolve `{"job": id}` (acompanhe em `/api/jobs/{id}`) |
| POST | `/api/imagem/pesquisar` | `{"imagem": "<id>", "foco": "", "job": false}` → `{"texto", "fontes": [{"n", "titulo", "referencia", ...}], "consultas", "descricao", "reversa", "avisos"}` |
| POST | `/api/chats/{id}/mensagens` | novos campos `"imagens": ["<id>"]` e `"acao_imagem": "minucioso\|geral\|texto\|pixel\|pesquisar"` |
| POST | `/api/upload` | arquivo de imagem com destino `chat` agora devolve `"tipo": "imagem"` + `id` |
