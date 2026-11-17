"""Ferramentas dos kits (v0.6): pixel art e ABNT. Só ficam visíveis ao agente com kits.<kit>.ativo = true.

Esquemas simples (um campo `operacao`) para modelos pequenos acertarem as chamadas.
Leitura: dentro das pastas permitidas; escrita: só no workspace (mesma política das outras ferramentas)."""
from __future__ import annotations

import json
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .registro import ferramenta


class ArgsPixelImagem(BaseModel):
    operacao: Literal["redimensionar", "upscale", "remover_fundo", "aplicar_paleta", "reduzir_paleta", "extrair_paleta",
                      "preview"] = Field(description="o que fazer com a imagem")
    entrada: str = Field(description="arquivo de imagem (.png/.gif/.jpg/.aseprite)")
    saida: str = Field("", description="arquivo de saída .png (vazio = ao lado da entrada com sufixo)")
    largura: int = Field(0, description="redimensionar: nova largura em px (ex.: 32)")
    altura: int = Field(0, description="redimensionar: nova altura (0 = proporcional)")
    fator: float = Field(0, description="upscale/preview: fator inteiro (ex.: 4); redimensionar: fator (ex.: 0.25)")
    paleta: str = Field("", description="pico-8 | db16 | db32 | endesga-32 | gameboy | 1bit | arquivo .gpl/.hex")
    cores: int = Field(16, description="reduzir_paleta: número de cores")
    dither: bool = False
    cor_fundo: str = Field("", description="remover_fundo: cor #rrggbb (vazio = canto superior esquerdo)")
    tolerancia: int = 0


def _saida(ctx, a, sufixo: str):
    from pathlib import Path

    if a.saida:
        return ctx.politica.checar_escrita(a.saida)
    p = Path(a.entrada)
    return ctx.politica.checar_escrita(str(p.with_name(f"{p.stem}-{sufixo}.png")))


@ferramenta("pixel_imagem", "Pixel art: redimensiona (nearest), amplia, remove fundo, aplica/reduz/extrai paleta ou "
            "gera preview de uma imagem. Sem borrar pixels.", permissao="escrita", grupos={"pixel"})
def pixel_imagem(ctx, a: ArgsPixelImagem) -> str:
    from ..kits import paletas as P
    from ..kits import pixel as X

    ent = ctx.politica.checar_leitura(a.entrada)
    im = X.abrir(ent)
    op = a.operacao
    if op == "extrair_paleta":
        cores = X.extrair_paleta(im, 256)
        if a.saida:
            P.salvar_paleta(cores, ctx.politica.checar_escrita(a.saida))
        return f"{len(cores)} cor(es): " + ", ".join(P.rgb_para_hex(c) for c in cores[:64])
    if op == "redimensionar":
        out = X.redimensionar(im, a.largura, a.altura, a.fator if a.fator and a.fator < 1 else 0)
    elif op == "upscale":
        out = X.upscale(im, int(a.fator or 4))
    elif op == "remover_fundo":
        out = X.remover_fundo(im, a.cor_fundo or None, a.tolerancia)
    elif op == "aplicar_paleta":
        out = X.aplicar_paleta(im, a.paleta or ctx.cfg.kits.pixel.paleta_padrao, a.dither)
    elif op == "reduzir_paleta":
        out = X.reduzir_paleta(im, a.cores, a.dither)
    else:
        out = X.preview(im, int(a.fator or 0))
    extra = ""
    if a.paleta and op in ("redimensionar", "upscale", "remover_fundo"):  # modelos pequenos juntam passos numa chamada
        out = X.aplicar_paleta(out, a.paleta, a.dither)
        extra = f" + paleta {a.paleta}"
    dest = _saida(ctx, a, op)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest)
    return f"OK: {op}{extra} -> {dest} ({out.width}x{out.height})"


class ArgsPixelSheet(BaseModel):
    operacao: Literal["montar", "fatiar", "gif"] = Field(description="montar spritesheet, fatiar em quadros ou gerar GIF")
    entradas: List[str] = Field(default_factory=list, description="montar/gif: arquivos dos quadros, em ordem")
    entrada: str = Field("", description="fatiar/gif: uma spritesheet")
    saida: str = Field(description="montar: .png (gera .json junto); fatiar: pasta; gif: .gif")
    largura: int = Field(0, description="fatiar/gif a partir de sheet: largura do quadro")
    altura: int = Field(0, description="fatiar/gif a partir de sheet: altura do quadro")
    colunas: int = 0
    duracao_ms: int = 100
    fator: int = Field(1, description="gif: ampliação inteira")


@ferramenta("pixel_spritesheet", "Pixel art: monta spritesheet (+JSON no formato do Aseprite), fatia uma sheet em "
            "quadros ou gera GIF animado.", permissao="escrita", grupos={"pixel"})
def pixel_spritesheet(ctx, a: ArgsPixelSheet) -> str:
    from ..kits import pixel as X

    if a.operacao == "fatiar" or (a.operacao == "gif" and a.entrada):
        sheet = X.abrir(ctx.politica.checar_leitura(a.entrada))
        if not (a.largura and a.altura):
            return "Informe largura e altura do quadro."
        quadros = X.fatiar(sheet, a.largura, a.altura)
    else:
        quadros = [X.abrir(ctx.politica.checar_leitura(e)) for e in a.entradas]
    if not quadros:
        return "Nenhum quadro."
    if a.operacao == "fatiar":
        pasta = ctx.politica.checar_escrita(a.saida)
        pasta.mkdir(parents=True, exist_ok=True)
        for i, q in enumerate(quadros):
            q.save(pasta / f"quadro_{i:03d}.png")
        return f"OK: {len(quadros)} quadro(s) em {pasta}"
    if a.operacao == "gif":
        dest = ctx.politica.checar_escrita(a.saida)
        X.gif(quadros, dest, a.duracao_ms, a.fator)
        return f"OK: GIF com {len(quadros)} quadro(s) -> {dest}"
    dest = ctx.politica.checar_escrita(a.saida)
    folha, meta = X.montar(quadros, a.colunas, duracao_ms=a.duracao_ms)
    meta["meta"]["image"] = dest.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    folha.save(dest)
    dest.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return f"OK: sheet {folha.width}x{folha.height} com {len(quadros)} quadro(s) -> {dest} (+ .json)"


class ArgsAseprite(BaseModel):
    operacao: Literal["info", "exportar_png", "exportar_sheet", "script"] = "info"
    arquivo: str = Field("", description=".ase/.aseprite")
    saida: str = Field("", description="png de saída (sheet: o .json vai junto)")
    escala: int = 1
    tag: str = ""
    script: str = Field("", description="script: arquivo .lua ou nome de um pronto (aplicar_paleta.lua, "
                                        "exportar_camadas.lua, redimensionar.lua)")
    parametros: str = Field("", description="script: chave=valor separados por ;")


@ferramenta("pixel_aseprite", "Usa o Aseprite (modo --batch) para exportar .aseprite em PNG/spritesheet+JSON ou rodar "
            "script Lua. Sem Aseprite instalado, exporta com o leitor embutido.", permissao="execucao", grupos={"pixel"})
def pixel_aseprite(ctx, a: ArgsAseprite) -> str:
    from ..kits import pixel as X

    ase = X.Aseprite(X.detectar_aseprite(ctx.cfg.kits.pixel.aseprite))
    if a.operacao == "info":
        return (f"Aseprite: {ase.exe} ({ase.versao()})" if ase.disponivel else
                "Aseprite não encontrado; uso o leitor .aseprite embutido (camadas normais, sem blend modes).")
    arq = ctx.politica.checar_leitura(a.arquivo)
    if ase.disponivel and a.operacao != "script":  # rodar programa externo = execução (pede aprovação/lista)
        ctx.politica.autorizar_comando(f"aseprite --batch {arq.name} --{a.operacao.replace('exportar_', '')}")
    if a.operacao == "exportar_png":
        saidas = ase.exportar_png(arq, ctx.politica.checar_escrita(a.saida or str(arq.with_suffix(".png"))), a.escala,
                                  tag=a.tag)
        return f"OK: {len(saidas)} PNG(s): " + ", ".join(str(s) for s in saidas[:10])
    if a.operacao == "exportar_sheet":
        png, js = ase.exportar_sheet(arq, ctx.politica.checar_escrita(a.saida or str(arq.with_suffix(".sheet.png"))),
                                     escala=a.escala, tag=a.tag)
        return f"OK: {png} + {js}" + ("" if ase.disponivel else " (leitor embutido)")
    if not ase.disponivel:
        return "Scripts Lua precisam do Aseprite instalado (configure kits.pixel.aseprite)."
    from pathlib import Path

    scr = Path(a.script)
    if a.script in X.SCRIPTS_LUA:
        scr = X.salvar_scripts_lua(ctx.politica.checar_escrita("scripts_aseprite"))[list(X.SCRIPTS_LUA).index(a.script)]
    else:
        scr = ctx.politica.checar_leitura(a.script)
    params = dict(p.split("=", 1) for p in a.parametros.split(";") if "=" in p)
    ctx.politica.autorizar_comando(f"aseprite --batch {arq.name} --script {scr.name}")
    return ase.rodar_script(scr, params, arq) or "OK"


class ArgsRefPixel(BaseModel):
    tema: str = Field(description="o que procurar (ex.: 'animação de corrida 8 direções', 'paleta para floresta')")


@ferramenta("pixel_referencias", "Pesquisa na web tutoriais e referências de pixel art/Aseprite sobre um tema (cite [n]).",
            permissao="rede", grupos={"pixel"})
def pixel_referencias(ctx, a: ArgsRefPixel) -> str:
    from ..i18n import idioma_atual
    from ..kits.pixel import consultas_referencia

    fontes = []
    for q in consultas_referencia(a.tema, idioma_atual())[:2]:
        fontes += ctx.web.pesquisar(q, status=lambda s: ctx.evento("status", s))
    vistos, unicas = set(), []
    for f in fontes:
        if f.referencia not in vistos:
            vistos.add(f.referencia)
            unicas.append(f)
    if not unicas:
        return "A busca não trouxe resultados."
    unicas = ctx.adicionar_fontes(unicas[:6])
    return "Referências (cite como [n]):\n\n" + "\n\n".join(f.bloco(700) for f in unicas)


# ------------------------------------------------------------------ ABNT
class ArgsAbntRef(BaseModel):
    identificador: str = Field(description="DOI (10.xxxx/...), ISBN ou URL")
    pagina: str = Field("", description="página para a citação (opcional)")


@ferramenta("abnt_referencia", "Gera a referência ABNT (NBR 6023) e a citação autor-data (NBR 10520) a partir de DOI, "
            "ISBN ou URL.", permissao="rede", grupos={"abnt"})
def abnt_referencia(ctx, a: ArgsAbntRef) -> str:
    from ..kits import abnt as A

    r = A.identificar(a.identificador)
    ref = A.formatar_referencia(r)
    cit = A.citacao(r, a.pagina, norma=ctx.cfg.kits.abnt.norma_citacao)
    av = f"\nConfira: {'; '.join(r.avisos)}" if r.avisos else ""
    return f"Referência: {ref}\nCitação: {cit} | narrativa: {A.citacao(r, a.pagina, True, ctx.cfg.kits.abnt.norma_citacao)}{av}"


class ArgsAbntDoc(BaseModel):
    entrada: str = Field(description="texto em markdown (.md) com # títulos; citações já no formato (Autor, ano)")
    saida: str = Field(description="arquivo .docx de saída")
    titulo: str
    autor: str = ""
    referencias: List[str] = Field(default_factory=list, description="DOIs/ISBNs/URLs das obras citadas")
    subtitulo: str = ""
    natureza: str = ""


@ferramenta("abnt_documento", "Gera um .docx no padrão ABNT NBR 14724 (capa, folha de rosto, sumário, margens 3/2, "
            "fonte 12, espaço 1,5, referências em ordem alfabética).", permissao="escrita", grupos={"abnt"})
def abnt_documento(ctx, a: ArgsAbntDoc) -> str:
    from ..kits import abnt as A

    k = ctx.cfg.kits.abnt
    md = ctx.politica.checar_leitura(a.entrada).read_text(encoding="utf-8")
    refs, falhas = [], []
    for i in a.referencias:
        try:
            refs.append(A.identificar(i))
        except Exception as e:  # noqa: BLE001
            falhas.append(f"{i}: {e}")
    t = A.Trabalho(titulo=a.titulo, subtitulo=a.subtitulo, autor=a.autor or k.autor or "Autor", instituicao=k.instituicao,
                   curso=k.curso, local=k.local, natureza=a.natureza, fonte=k.fonte)
    dest = A.gerar_docx(t, md, refs, ctx.politica.checar_escrita(a.saida))
    return f"OK: {dest} ({len(refs)} referência(s))" + (f"\nNão encontrei: {'; '.join(falhas)}" if falhas else "")
