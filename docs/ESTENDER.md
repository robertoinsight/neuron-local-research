# Como estender

## 1. Nova ferramenta (plugin)

Crie um arquivo `.py` na pasta `plugins/` (configurável em `plugins.pastas`). Ele é carregado automaticamente.

```python
# plugins/cotacao.py
from pydantic import BaseModel, Field
from nlr.ferramentas.registro import ferramenta


class Args(BaseModel):
    moeda: str = Field(description="código da moeda, ex.: USD")


@ferramenta("cotacao", "Consulta a cotação de uma moeda em reais.", permissao="rede", grupos={"pesquisa"})
def cotacao(ctx, args: Args) -> str:
    import requests
    r = requests.get(f"https://economia.awesomeapi.com.br/json/last/{args.moeda}-BRL", timeout=10)
    d = r.json()[f"{args.moeda}BRL"]
    return f"1 {args.moeda} = R$ {d['bid']}"
```

- O **2º parâmetro** (modelo Pydantic) define os argumentos: o esquema JSON é mostrado ao modelo e os argumentos são validados antes da chamada.
- Retorne **texto**. Exceções viram `ERRO: ...` para o modelo tentar de novo; `PermissaoNegada` vira `PERMISSÃO NEGADA: ...`.
- `grupos` decide quais sub-agentes dos projetos enxergam a ferramenta: `pesquisa` (pesquisador e redator), `codigo` (desenvolvedor), `arquivos`, `memoria`, `mcp`; `util` (padrão) = todos. No chat (`/agente`) todas aparecem.
- Use o `ctx` para respeitar a segurança: `ctx.politica.checar_escrita(caminho)`, `ctx.politica.checar_leitura(caminho)`, `ctx.workspace`, `ctx.evento("status", "...")`, `ctx.adicionar_fontes([...])` para gerar citações.
- Um plugin também pode definir `def registrar(registro): ...` para registrar ferramentas manualmente.
- Pacotes instalados com *entry point* no grupo `nlr.ferramentas` também são carregados.

Confira com `nlr ferramentas`.

## 2. Servidores MCP

Qualquer servidor MCP via *stdio* (o mesmo formato do `mcp.json` do LM Studio/Claude Desktop):

```yaml
mcp:
  timeout: 60
  servidores:
    arquivos:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/SeuNome/Documents"]
      permissao: confirmar      # pergunta antes de cada uso (padrão)
    meu-local-agent:
      command: C:/IA/local-agent/.venv/Scripts/python.exe
      args: ["C:/IA/local-agent/mcp_server.py"]
      permissao: livre          # roda sem perguntar
```

As ferramentas aparecem como `mcp_<servidor>__<ferramenta>` (veja com `nlr ferramentas --mcp`) e ficam disponíveis no chat (`/agente`) e nos projetos. Um servidor que falha ao iniciar não derruba o agente; o erro aparece no `nlr doctor`.

## 3. Novo backend de modelos

Qualquer servidor com API compatível com a da OpenAI (`/v1/chat/completions`, `/v1/embeddings`, `/v1/models`) funciona com `backend: openai_compat` e `base_url`. Exemplos: vLLM, LocalAI, KoboldCpp, Jan, text-generation-webui, OpenRouter, Groq.

Para um backend com particularidades, edite `nlr/config.py` (`BACKENDS_PADRAO`), `nlr/config_modelo.py` (`PRESETS`) e, se precisar, `nlr/llm/cliente.py` (`DICAS_BACKEND` para mensagens de erro; `_extras_pensamento` para desligar o "pensamento").

## 4. Novo papel de sub-agente

Em `nlr/prompts.py`, acrescente em `PAPEIS` (o texto do papel) e em `nlr/agentes/projeto.py` ligue um tipo de tarefa a ele (`PAPEL_POR_TIPO`) e defina quais grupos de ferramentas ele vê (`GRUPOS_POR_PAPEL`). Inclua o novo tipo na descrição do `PROMPT_PLANEJADOR` para o planejador poder usá-lo.

## 5. Novo nó no fluxo de projeto

O grafo está em `ExecutorProjeto._construir()` (`agentes/projeto.py`). Exemplo de nó extra "testar" entre a última tarefa e o relatório:

```python
g.add_node("testar", self.no_testar)        # def no_testar(self, estado) -> dict: ...
g.add_conditional_edges("executar", lambda s: "revisar" if s.get("atual") is not None else "testar",
                        {"revisar": "revisar", "testar": "testar"})
g.add_edge("testar", "finalizar")
```

Cada nó recebe e devolve (parcialmente) o `EstadoProjeto`; o checkpoint é automático.

## 6. Novo formato de arquivo na biblioteca

Em `nlr/biblioteca/carregadores.py`, escreva uma função que devolva `List[Segmento(texto, local, tipo)]` e registre a extensão no dicionário de carregadores; acrescente a extensão em `biblioteca.extensoes`.

## 7. Usar como biblioteca Python

```python
from nlr.config import carregar
from nlr.servicos import Servicos
from nlr.agentes.pesquisa import pesquisar

serv = Servicos(carregar("config.yaml"))
ctx = serv.contexto(serv.cfg.dir_dados / "area_de_trabalho")
r = pesquisar(ctx, "o que meus documentos dizem sobre X?", usar_web=False)
print(r.texto_completo())
```

## 8. Testes

```bash
.venv/bin/python -m pytest -q                  # tudo (usa um servidor de modelo FALSO, rápido)
.venv/bin/python -m pytest -q -m "not rede"    # sem internet
```

O servidor falso (`tests/servidor_falso.py`) imita a API OpenAI e responde de forma roteirizada a cada tipo de prompt; use-o para testar novas ferramentas e nós sem precisar de GPU.
