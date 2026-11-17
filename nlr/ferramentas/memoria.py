"""Ferramentas de memória de longo prazo."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .registro import ferramenta


class ArgsLembrar(BaseModel):
    texto: str = Field(description="fato curto e autocontido para lembrar no futuro")
    tipo: Literal["fato", "preferencia", "decisao", "licao"] = "fato"


@ferramenta("lembrar", "Guarda um fato/preferência/decisão/lição na memória de longo prazo.", permissao="memoria",
            grupos={"memoria", "pesquisa", "codigo"})
def lembrar(ctx, a: ArgsLembrar) -> str:
    if ctx.memoria is None:
        return "Memória indisponível."
    lid = ctx.memoria.lembrar(a.texto, a.tipo, ctx.escopo_gravacao, origem="ferramenta")
    return f"OK: memorizado (id {lid})."


class ArgsRecordar(BaseModel):
    consulta: str = Field(description="assunto a procurar na memória")


@ferramenta("recordar", "Procura na memória de longo prazo (conversas e projetos anteriores).", permissao="memoria",
            grupos={"memoria", "pesquisa", "codigo"})
def recordar(ctx, a: ArgsRecordar) -> str:
    if ctx.memoria is None:
        return "Memória indisponível."
    itens = ctx.memoria.recordar(a.consulta, ctx.escopos_memoria)
    if not itens:
        return "Nada relevante na memória."
    return "\n".join(f"- ({i.tipo}, {i.escopo}) {i.texto}" for i in itens)
