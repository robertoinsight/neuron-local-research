"""Ferramentas de pesquisa: biblioteca local (RAG híbrido) e internet (somente leitura)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..biblioteca.busca import buscar
from ..fontes import Fonte
from .registro import ferramenta


class ArgsBusca(BaseModel):
    consulta: str = Field(description="o que procurar (palavras-chave ou pergunta)")
    k: int = Field(6, description="quantidade de trechos")


@ferramenta("buscar_biblioteca", "Busca trechos relevantes nos documentos da biblioteca local do usuário (com citação).",
            permissao="leitura", grupos={"pesquisa", "codigo"})
def buscar_biblioteca(ctx, a: ArgsBusca) -> str:
    st = ctx.indice.status()
    if st["trechos"] == 0:
        return "A biblioteca está vazia ou não foi indexada (rode: nlr indexar)."
    res = buscar(ctx.indice, a.consulta, k=max(1, min(a.k, 12)))
    if not res:
        return "Nenhum trecho encontrado na biblioteca para essa consulta. Tente outras palavras."
    fontes = ctx.adicionar_fontes([
        Fonte(n=0, tipo="biblioteca", titulo=r.rotulo.split(" (")[0], referencia=r.caminho, texto=r.texto, local=r.local)
        for r in res])
    return "Trechos da biblioteca (cite como [n]):\n\n" + "\n\n".join(f.bloco(1200) for f in fontes)


class ArgsWeb(BaseModel):
    consulta: str = Field(description="consulta para o buscador (curta, em português ou inglês)")


@ferramenta("buscar_web", "Pesquisa na internet, lê as melhores páginas e devolve trechos com URL (cite como [n]).",
            permissao="rede", grupos={"pesquisa"})
def buscar_web(ctx, a: ArgsWeb) -> str:
    fontes = ctx.web.pesquisar(a.consulta, status=lambda s: ctx.evento("status", s))
    if not fontes:
        return "A busca não trouxe resultados. Tente outra consulta."
    fontes = ctx.adicionar_fontes(fontes)
    return "Resultados da web (cite como [n]):\n\n" + "\n\n".join(f.bloco(1200) for f in fontes)


class ArgsPagina(BaseModel):
    url: str = Field(description="endereço http(s) da página")


@ferramenta("ler_pagina", "Baixa uma página da web e devolve o texto principal (somente leitura).",
            permissao="rede", grupos={"pesquisa"})
def ler_pagina(ctx, a: ArgsPagina) -> str:
    pg = ctx.web.ler_pagina(a.url)
    if not pg.texto.strip():
        return f"Não consegui extrair texto de {a.url} (página bloqueada, vazia ou feita em JavaScript)."
    f = ctx.adicionar_fontes([Fonte(n=0, tipo="web", titulo=pg.resultado.titulo, referencia=a.url, texto=pg.texto)])[0]
    return f"[{f.n}] {a.url}\n{pg.texto[:8000]}"
