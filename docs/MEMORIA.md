# Memória de longo prazo (v0.5)

## Escopos
- `global`: vale para todos os chats.
- `projeto:<nome>`: vale só para os chats daquele projeto.

Na interface, o botão **🧠** no topo do chat liga o chat a um projeto. As continuações automáticas (handoff) herdam o projeto.
Um chat de projeto lembra fatos `global` + `projeto:<nome>` e grava os novos no projeto.

## Marca de origem (coerente com o guard de inhearsay)
Cada fato tem uma `marca`:

| marca | significado | usado nas respostas? |
|---|---|---|
| `usuario` (literal) | escrito por você, confirmado por você ou apoiado no que você escreveu (a evidência fica guardada) | sim, como `[usuário: literal]` |
| `inferido` | dedução do agente/modelo | sim, como `[inferido]` (use com cautela) |
| `inhearsay` | atribui a você algo que você não disse ("o usuário aprovou...") ou perdeu uma condição | **não** |

Como a extração automática funciona:
1. Frases suas em 1ª pessoa ("prefiro…", "estou criando…", "decidi…") viram fatos literais sem usar o modelo. Frases condicionais ("se…", "talvez") ficam de fora.
2. O modelo sugere outros fatos, e cada um passa pelo verificador de inhearsay contra as suas mensagens literais.
3. No perfil `pequeno`, o modelo só vê as suas mensagens. Modelos de 0.5–3B copiavam os conselhos do assistente como se fossem fatos.
4. Uma "decisão" com condição é rebaixada para "fato".

## Deduplicação
- Fato parecido no mesmo escopo (palavras iguais ou um contido no outro, com os mesmos números) não duplica. Ele é reforçado: `usos+1`.
- Se o novo for literal, o fato existente é promovido para `usuario`.
- Com embeddings, fatos com similaridade > 0.95 também são considerados iguais.

## Esquecimento
`nlr memoria esquecer-antigos`, ou o botão 🧹 na página Memória:
- Apaga fatos **inferidos** não usados há `memoria.dias_para_esquecer` dias (padrão 90). O prazo cresce com o uso, e o de inhearsay é metade.
- Corta o excesso acima de `memoria.max_por_escopo` (padrão 300), começando pelos menos usados.
- Fatos **literais** e **fixados** (📌) nunca são esquecidos automaticamente.

## Ver e editar
- **Interface → Memória:**
  - buscar e filtrar por escopo;
  - adicionar um fato (vira literal);
  - editar ✎ (o texto editado vira literal);
  - fixar 📌;
  - ✓ confirmar (inferido/inhearsay → literal);
  - apagar 🗑.
- **CLI:** `nlr memoria listar | adicionar | buscar | editar <id> [--texto --escopo --fixar --confirmar] | esquecer <id> | esquecer-antigos`.
- **API:** `GET/POST /api/memoria`, `PATCH/DELETE /api/memoria/{id}`, `POST /api/memoria/esquecer`, `PATCH /api/chats/{id} {"projeto": "..."}`.

Bancos antigos são migrados sozinhos (colunas novas). Fatos que você mesmo tinha guardado viram `usuario`.
