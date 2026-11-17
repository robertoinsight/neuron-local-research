"""Fonte numerada usada nas citações [1], [2]... (web ou biblioteca)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class Fonte:
    n: int
    tipo: str  # "web" | "biblioteca" | "memoria"
    titulo: str
    referencia: str  # URL ou caminho do arquivo
    texto: str
    local: str = ""

    def cabecalho(self) -> str:
        if self.tipo == "web":
            return f"[{self.n}] (web) {self.titulo} — {self.referencia}"
        if self.tipo == "memoria":
            return f"[{self.n}] (memória) {self.titulo}"
        loc = f", {self.local}" if self.local else ""
        return f"[{self.n}] (biblioteca) {self.titulo}{loc}"

    def bloco(self, max_chars: int = 1800) -> str:
        return f"{self.cabecalho()}\n{self.texto[:max_chars]}"


def renumerar(fontes: List[Fonte], inicio: int = 1) -> List[Fonte]:
    for i, f in enumerate(fontes):
        f.n = inicio + i
    return fontes


def lista_referencias(fontes: List[Fonte]) -> str:
    return "\n".join(f.cabecalho() for f in fontes)
