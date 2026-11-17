"""Cliente MCP: usa ferramentas de servidores MCP (stdio) como se fossem ferramentas do agente.

Configure em config.yaml (mesmo formato do mcp.json do LM Studio):

    mcp:
      servidores:
        local-agent:
          command: C:/caminho/local-agent/.venv/Scripts/python.exe
          args: ["C:/caminho/local-agent/mcp_server.py"]
          permissao: livre   # ou "confirmar" (padrão): pergunta antes de cada chamada

As ferramentas aparecem como  mcp_<servidor>__<ferramenta>.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
from concurrent.futures import Future
from typing import Dict, List, Optional

from ..config import Config, ServidorMCP
from ..erros import AgenteErro, PermissaoNegada
from .registro import Ferramenta, Registro

log = logging.getLogger(__name__)


def _errlog():
    import os
    import sys

    for f in (sys.stderr, sys.__stderr__):
        try:
            if f is not None:
                f.fileno()
                return f
        except Exception:  # noqa: BLE001
            pass
    return open(os.devnull, "w")  # noqa: SIM115


def _nome_seguro(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)


class _Conexao:
    def __init__(self, nome: str, srv: ServidorMCP, timeout: float):
        self.nome = nome
        self.srv = srv
        self.timeout = timeout
        self.fila: Optional[asyncio.Queue] = None
        self.pronto = threading.Event()
        self.erro: Optional[BaseException] = None
        self.ferramentas: List = []

    async def rodar(self):
        from mcp import Client, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=self.srv.command, args=list(self.srv.args),
                                       env=dict(self.srv.env) or None, cwd=self.srv.cwd)
        self.fila = asyncio.Queue()
        try:
            # o padrão do mcp (errlog=sys.stderr) é fixado na importação; se o stderr daquele momento não tem
            # fileno (pythonw no Windows, CliRunner, interface), o servidor nem inicia ("fileno").
            async with Client(stdio_client(params, errlog=_errlog()), read_timeout_seconds=self.timeout) as c:
                self.ferramentas = list((await c.list_tools()).tools)
                self.pronto.set()
                while True:
                    item = await self.fila.get()
                    if item is None:
                        break
                    nome, args, fut = item
                    try:
                        r = await c.call_tool(nome, args)
                        fut.set_result(r)
                    except BaseException as e:  # noqa: BLE001
                        fut.set_exception(e)
        except BaseException as e:  # noqa: BLE001
            self.erro = e
            self.pronto.set()


class GerenciadorMCP:
    """Mantém as conexões MCP abertas numa thread com loop asyncio próprio."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True, name="mcp-loop")
        self.thread.start()
        self.conexoes: Dict[str, _Conexao] = {}
        self.erros: Dict[str, str] = {}

    def conectar(self) -> None:
        for nome, srv in self.cfg.mcp.servidores.items():
            con = _Conexao(nome, srv, self.cfg.mcp.timeout)
            asyncio.run_coroutine_threadsafe(con.rodar(), self.loop)
            if not con.pronto.wait(timeout=self.cfg.mcp.timeout):
                self.erros[nome] = "o servidor não respondeu a tempo"
                continue
            if con.erro:
                self.erros[nome] = f"{type(con.erro).__name__}: {con.erro}"
                log.warning("Servidor MCP '%s' falhou: %s", nome, con.erro)
                continue
            self.conexoes[nome] = con

    def chamar(self, servidor: str, ferramenta: str, args: dict) -> str:
        con = self.conexoes.get(servidor)
        if con is None:
            raise AgenteErro(f"Servidor MCP '{servidor}' não está conectado.")
        fut: Future = Future()

        def enfileirar():
            con.fila.put_nowait((ferramenta, args, fut))

        self.loop.call_soon_threadsafe(enfileirar)
        r = fut.result(timeout=self.cfg.mcp.timeout + 5)
        partes = []
        for bloco in getattr(r, "content", []) or []:
            t = getattr(bloco, "text", None)
            if t is not None:
                partes.append(t)
            else:
                partes.append(f"[conteúdo {getattr(bloco, 'type', '?')} omitido]")
        texto = "\n".join(partes) or str(getattr(r, "structuredContent", "") or "(sem conteúdo)")
        if getattr(r, "isError", False) or getattr(r, "is_error", False):
            return "ERRO (servidor MCP): " + texto
        return texto

    def registrar_em(self, registro: Registro) -> List[str]:
        nomes = []
        for srv_nome, con in self.conexoes.items():
            permissao_livre = self.cfg.mcp.servidores[srv_nome].permissao == "livre"
            for t in con.ferramentas:
                nome = f"mcp_{_nome_seguro(srv_nome)}__{_nome_seguro(t.name)}"
                schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {"type": "object"}

                def fn(ctx, args, _s=srv_nome, _t=t.name, _livre=permissao_livre):
                    if not _livre:
                        conf = ctx.politica.confirmar if ctx is not None else None
                        if conf is None:
                            raise PermissaoNegada(
                                f"A ferramenta MCP {_s}/{_t} precisa de confirmação. Marque o servidor com "
                                "permissao: livre no config.yaml para liberar sem perguntar.")
                        if not conf("Usar ferramenta MCP?", f"{_s} / {_t}\nargumentos: {args}"):
                            raise PermissaoNegada(f"O usuário não autorizou {_s}/{_t}.")
                    return self.chamar(_s, _t, dict(args or {}))

                registro.registrar(Ferramenta(nome=nome, descricao=(t.description or t.name)[:400], funcao=fn,
                                              schema=schema, permissao="mcp", grupos={"mcp", "pesquisa", "codigo"},
                                              origem=f"mcp:{srv_nome}"))
                nomes.append(nome)
        return nomes

    def fechar(self) -> None:
        for con in self.conexoes.values():
            if con.fila is not None:
                self.loop.call_soon_threadsafe(con.fila.put_nowait, None)
        self.loop.call_soon_threadsafe(self.loop.stop)
