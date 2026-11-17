"""Monta os serviços do agente (modelo, memória, biblioteca, ferramentas, MCP) a partir da configuração."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, List, Optional

from .biblioteca.embeddings import criar_embedder
from .biblioteca.indice import IndiceBiblioteca
from .config import Config
from .ferramentas.contexto import ContextoFerramentas
from .ferramentas.registro import REGISTRO_PADRAO, Registro, carregar_embutidas, carregar_plugins
from .ferramentas.seguranca import Politica
from .llm.cliente import ClienteLLM
from .memoria.armazenamento import Memoria

log = logging.getLogger(__name__)

Eventos = Callable[[str, str], None]
Confirmar = Callable[[str, str], bool]


class Servicos:
    def __init__(self, cfg: Config, eventos: Optional[Eventos] = None, confirmar: Optional[Confirmar] = None,
                 usar_mcp: bool = False):
        self.cfg = cfg
        self.eventos = eventos or (lambda t, m: None)
        self.confirmar = confirmar
        self.llm = ClienteLLM(cfg, eventos=lambda m: self.eventos("aviso", m))
        self.embedder = criar_embedder(cfg, self.llm)
        self.memoria = Memoria(cfg, self.embedder)
        self._indice: Optional[IndiceBiblioteca] = None
        carregar_embutidas()
        self.plugins = carregar_plugins([cfg.resolver(p) for p in cfg.plugins.pastas])
        self.registro: Registro = REGISTRO_PADRAO.copia()
        self.aplicar_kits()
        self.mcp = None
        self.ferramentas_mcp: List[str] = []
        if usar_mcp and cfg.mcp.servidores:
            self.conectar_mcp()

    def aplicar_kits(self) -> None:
        """Kits desligados (config kits.<kit>.ativo) não aparecem para o agente."""
        for kit, ativo in (("pixel", self.cfg.kits.pixel.ativo), ("abnt", self.cfg.kits.abnt.ativo)):
            for f in REGISTRO_PADRAO.listar([kit]):
                if ativo:
                    self.registro.registrar(f)
                else:
                    self.registro.remover(f.nome)

    @property
    def indice(self) -> IndiceBiblioteca:
        if self._indice is None:
            self._indice = IndiceBiblioteca(self.cfg, self.embedder)
        return self._indice

    def conectar_mcp(self) -> List[str]:
        from .ferramentas.mcp_cliente import GerenciadorMCP

        if self.mcp is None:
            self.mcp = GerenciadorMCP(self.cfg)
            self.mcp.conectar()
            self.ferramentas_mcp = self.mcp.registrar_em(self.registro)
            for nome, erro in self.mcp.erros.items():
                self.eventos("aviso", f"Servidor MCP '{nome}' indisponível: {erro}")
        return self.ferramentas_mcp

    def contexto(self, workspace: Path, escopos: Optional[List[str]] = None, escopo_gravacao: str = "global",
                 eventos: Optional[Eventos] = None, confirmar: Optional[Confirmar] = None) -> ContextoFerramentas:
        pol = Politica(self.cfg, workspace, confirmar=confirmar if confirmar is not None else self.confirmar)
        ctx = ContextoFerramentas(cfg=self.cfg, politica=pol, llm=self.llm, memoria=self.memoria,
                                  escopos_memoria=escopos or ["global"], escopo_gravacao=escopo_gravacao,
                                  eventos=eventos or self.eventos)
        ctx._indice = self.indice
        return ctx

    def fechar(self) -> None:
        if self.mcp:
            self.mcp.fechar()
        if self._indice:
            self._indice.fechar()
        self.memoria.fechar()
