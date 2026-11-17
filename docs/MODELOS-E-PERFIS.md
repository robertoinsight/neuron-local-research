# Modelos, perfis e confiabilidade (fase 1)

## Detecção automática

Na primeira chamada, o NLR pergunta ao servidor quais modelos existem e quais estão carregados:

| Servidor | O que o NLR lê |
|---|---|
| LM Studio | `GET /api/v0/models`: `state` (loaded/not-loaded), `type` (llm, vlm, embeddings), `max_context_length`, `loaded_context_length` |
| Ollama | `/api/tags` (baixados), `/api/ps` (carregados e contexto em uso), `/api/show` (contexto máximo e `num_ctx`) |
| llama.cpp | `/props` (`n_ctx`) e `/v1/models` |
| Outros (OpenAI-compatível) | `/v1/models`; o contexto vem do `config.yaml` |

Regras do `modelo_chat: auto`:
1. Se há um modelo de chat **carregado**, usa ele.
2. Se não, escolhe o **maior** que cabe no seu PC (pela VRAM/RAM detectadas e pelo tamanho no nome, ex.: `9b`, `e4b`) e avisa.
3. Embeddings em `auto`: o primeiro modelo do tipo embeddings (carregado de preferência).

O contexto real substitui `contexto_tokens` (desligue com `contexto_auto: false`). Depois da primeira resposta,
o NLR confere de novo (o modelo já está carregado) e corrige o número se o servidor usou outro valor.

Veja tudo com `nlr modelos`, `nlr hardware` e `nlr doctor`.

## Perfis

| Perfil | Quando | Ferramentas por passo | Passos | Observação mantida | Tentativas de JSON |
|---|---|---|---|---|---|
| pequeno | < 5B ou contexto < 4,5 mil | 5 | 8 | 2.500 caracteres | 4 |
| medio | 5–15B | 9 | 12 | 6.000 | 3 |
| grande | > 15B | 20 | 20 | 12.000 | 2 |

O tamanho máximo da resposta fica em no máximo 1/4 do contexto. Force um perfil com `modelo.perfil: grande`.

## Roteador de ferramentas

Antes de cada tarefa, o NLR dá uma nota a cada ferramenta comparando as palavras do pedido com nome, descrição e
grupo, e mostra ao modelo só as melhores (o limite vem do perfil). Se o modelo pedir uma ferramenta que existe mas
ficou de fora, ela é liberada na hora.

## Erros que ensinam e anti-loop

- Argumentos inválidos geram uma mensagem com **o que está errado + um exemplo JSON pronto** da chamada correta.
- Nome de ferramenta digitado errado com uma única opção parecida (ex.: `leer_arquivo`) é corrigido sozinho.
- Se o modelo finalizar copiando o exemplo do prompt sem fazer nada, ele recebe um erro e tenta de novo (uma vez).
- Anti-loop: a mesma ação 2 vezes = aviso; 3 vezes = para e devolve o progresso. Alternar A-B-A-B-A-B = aviso.
  4 erros seguidos = aviso pedindo para ler o erro.

## Novo chat automático (handoff)

O NLR estima os tokens do chat (histórico + resumo + prompt + espaço da resposta). Ao chegar a `handoff.limite`
(0,8 = 80%) do contexto real:
1. gera um **resumo de passagem** (objetivo, decisões, feito, pendências, detalhes) a partir do estado salvo;
   se o modelo falhar, usa um resumo extrativo, sem modelo;
2. copia **literalmente** os primeiros pedidos do usuário (para nomes e objetivo nunca se perderem);
3. cria um chat novo ligado ao anterior (`pai`), com o resumo como mensagem de sistema e as 2 últimas mensagens.

O chat antigo continua salvo. Projetos (`nlr projeto ...`) já trabalham por tarefas a partir do estado salvo em disco,
então não dependem do tamanho do chat.

Teste real (CPU, qwen2.5 1.5B, contexto 4096): 13 mensagens, handoff aos 78%, e no chat novo o modelo respondeu
corretamente o nome do usuário e do jogo informados na primeira mensagem.

## Guarda inhearsay no handoff / Inhearsay guard (v0.4)

**PT** — Ao passar um chat longo para um novo (handoff), o resumo é verificado: itens atribuídos ao usuário ("você pediu…", ordens, condições) que não aparecem literalmente nas mensagens dele são marcados `[⚠ inhearsay: motivo]`; os demais viram `[usuário: literal]` ou `[agente: inferido]`. As últimas 6 mensagens do usuário são anexadas literalmente, com a regra de não tratar inferências como pedidos. Desligue com `handoff: {inhearsay: false}`.

**EN** — On handoff, the summary is checked: claims attributed to the user that don't appear in their actual messages are flagged `[⚠ inhearsay]`; the last 6 user messages are appended verbatim. Disable with `handoff.inhearsay: false`.
