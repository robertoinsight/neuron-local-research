"""Contexto compartilhado pelas ferramentas durante uma execução (projeto ou conversa)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Set

from ..config import Config
from ..fontes import Fonte
from .seguranca import Politica


@dataclass
class ContextoFerramentas:
    cfg: Config
    politica: Politica
    llm: object = None
    memoria: object = None
    escopos_memoria: List[str] = field(default_factory=lambda: ["global"])
    escopo_gravacao: str = "global"
    eventos: Optional[Callable[[str, str], None]] = None
    fontes: List[Fonte] = field(default_factory=list)
    arquivos_alterados: Set[str] = field(default_factory=set)
    comandos_executados: List[dict] = field(default_factory=list)
    _indice: object = None
    _web: object = None
    _mcp: object = None

    @property
    def workspace(self) -> Path:
        return self.politica.workspace

    def evento(self, tipo: str, msg: str) -> None:
        if self.eventos:
            self.eventos(tipo, msg)

    # serviços criados sob demanda (evita custo quando não usados)
    @property
    def indice(self):
        if self._indice is None:
            from ..biblioteca.embeddings import criar_embedder
            from ..biblioteca.indice import IndiceBiblioteca

            self._indice = IndiceBiblioteca(self.cfg, criar_embedder(self.cfg, self.llm))
        return self._indice

    @property
    def web(self):
        if self._web is None:
            from ..web.busca import PesquisaWeb

            self._web = PesquisaWeb(self.cfg)
        return self._web

    def adicionar_fontes(self, novas: List[Fonte]) -> List[Fonte]:
        """Numera as fontes novas na sequência global (reaproveita o número se a referência já existe)."""
        out = []
        for f in novas:
            existente = next((x for x in self.fontes if x.referencia == f.referencia and x.local == f.local), None)
            if existente:
                out.append(existente)
                continue
            f.n = len(self.fontes) + 1
            self.fontes.append(f)
            out.append(f)
        return out
