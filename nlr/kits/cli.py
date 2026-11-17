"""Comandos `nlr pixel ...`, `nlr abnt ...` e `nlr kits` (v0.6)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import typer
from rich.markup import escape
from rich.table import Table

pixel_app = typer.Typer(help="Kit Pixel Art: redimensionar, paletas, spritesheets, GIF, Aseprite.", no_args_is_help=True)
sheet_app = typer.Typer(help="Spritesheets: montar e fatiar.", no_args_is_help=True)
ase_app = typer.Typer(help="Aseprite (modo --batch) com fallback embutido.", no_args_is_help=True)
abnt_app = typer.Typer(help="Kit ABNT: referências (NBR 6023), citações (NBR 10520) e documento (NBR 14724).",
                       no_args_is_help=True)
pixel_app.add_typer(sheet_app, name="sheet")
pixel_app.add_typer(ase_app, name="aseprite")


def _c():
    from ..cli import console

    return console


def _cfg():
    from ..cli import _cfg as c

    return c()


def _saida(entrada: Path, saida: Optional[Path], sufixo: str, ext: str = ".png") -> Path:
    s = saida or entrada.with_name(f"{entrada.stem}-{sufixo}{ext}")
    s.parent.mkdir(parents=True, exist_ok=True)
    return s


def _ok(msg: str):
    _c().print(f"[green]✓[/] {escape(msg)}", highlight=False)


def _exigir(modulo: str, extra: str):
    import importlib

    try:
        importlib.import_module(modulo)
    except ImportError:
        _c().print(f"[red]✗[/] Falta a dependência opcional '{modulo}'. Instale com: "
                   f"pip install -e \".\\[{extra}]\"  (Windows: instalar.ps1 -Com{'Pixel' if extra == 'pixel' else 'ABNT'})")
        raise typer.Exit(1)


@pixel_app.callback()
def _pixel_cb(ctx: typer.Context):
    if ctx.invoked_subcommand not in ("paletas", "referencias", None):
        _exigir("PIL", "pixel")


@abnt_app.callback()
def _abnt_cb(ctx: typer.Context):
    if ctx.invoked_subcommand == "documento":
        _exigir("docx", "abnt")


# ------------------------------------------------------------------ pixel
@pixel_app.command("redimensionar")
def px_redim(entrada: Path, largura: int = typer.Option(0, help="nova largura (px)"),
             altura: int = typer.Option(0, help="nova altura (0 = proporcional)"),
             fator: float = typer.Option(0, help="ou fator (ex.: 0.25 = 128->32)"),
             saida: Optional[Path] = typer.Option(None, "-o", "--saida", help="arquivo de saída")):
    """Redimensiona com nearest-neighbor (sem borrar)."""
    from . import pixel as X

    im = X.redimensionar(X.abrir(entrada), largura, altura, fator)
    s = _saida(entrada, saida, f"{im.width}x{im.height}")
    im.save(s)
    _ok(f"{s} ({im.width}x{im.height})")


@pixel_app.command("upscale")
def px_up(entrada: Path, fator: int = typer.Option(4, help="fator inteiro"),
          saida: Optional[Path] = typer.Option(None, "-o", "--saida", help="arquivo de saída")):
    """Ampliação inteira (2x, 3x, 4x...)."""
    from . import pixel as X

    im = X.upscale(X.abrir(entrada), fator)
    s = _saida(entrada, saida, f"x{fator}")
    im.save(s)
    _ok(f"{s} ({im.width}x{im.height})")


@pixel_app.command("paleta")
def px_paleta(acao: str = typer.Argument(..., help="aplicar | reduzir | extrair"), entrada: Path = typer.Argument(...),
              paleta: str = typer.Option("", help="pico-8 | db16 | db32 | endesga-32 | gameboy | 1bit | .gpl/.hex/.pal"),
              cores: int = typer.Option(16, help="reduzir: número de cores"), dither: bool = typer.Option(False, help="pontilhado Floyd-Steinberg"),
              saida: Optional[Path] = typer.Option(None, "-o", "--saida", help="arquivo de saída")):
    """Aplica uma paleta, reduz o número de cores ou extrai a paleta (.gpl/.hex/.pal)."""
    from . import paletas as P
    from . import pixel as X

    im = X.abrir(entrada)
    if acao == "extrair":
        cs = X.extrair_paleta(im, 256)
        if saida:
            P.salvar_paleta(cs, saida, entrada.stem)
            _ok(f"{saida} ({len(cs)} cores)")
        _c().print(" ".join(P.rgb_para_hex(c) for c in cs), highlight=False)
        return
    if acao == "aplicar":
        out = X.aplicar_paleta(im, paleta or _cfg().kits.pixel.paleta_padrao, dither)
        suf = (paleta or "paleta").replace("/", "_").replace("\\", "_")
    elif acao == "reduzir":
        out = X.reduzir_paleta(im, cores, dither)
        suf = f"{cores}cores"
    else:
        raise typer.BadParameter("use aplicar | reduzir | extrair")
    s = _saida(entrada, saida, Path(suf).stem)
    out.save(s)
    _ok(str(s))


@pixel_app.command("paletas")
def px_paletas():
    """Lista as paletas embutidas."""
    from .paletas import PALETAS

    for n, cs in PALETAS.items():
        _c().print(f"[bold]{n}[/] ({len(cs)}): " + " ".join(f"[on #{c}]  [/]" for c in cs))


@pixel_app.command("fundo")
def px_fundo(entrada: Path, cor: str = typer.Option("", help="#rrggbb (vazio = canto superior esquerdo)"),
             tolerancia: int = typer.Option(0, help="0-255"),
             todo: bool = typer.Option(False, help="apaga a cor na imagem toda (não só a região ligada às bordas)"),
             saida: Optional[Path] = typer.Option(None, "-o", "--saida", help="arquivo de saída")):
    """Remove o fundo (fica transparente)."""
    from . import pixel as X

    out = X.remover_fundo(X.abrir(entrada), cor or None, tolerancia, contiguo=not todo)
    s = _saida(entrada, saida, "sem-fundo")
    out.save(s)
    _ok(str(s))


@pixel_app.command("preview")
def px_preview(entrada: Path, fator: int = typer.Option(0, help="0 = automático (~256 px)"),
               fundo: str = typer.Option("xadrez", help="xadrez ou #rrggbb"),
               saida: Optional[Path] = typer.Option(None, "-o", "--saida", help="arquivo de saída")):
    """Gera uma prévia ampliada sobre fundo xadrez."""
    from . import pixel as X

    out = X.preview(X.abrir(entrada), fator, fundo)
    s = _saida(entrada, saida, "preview")
    out.save(s)
    _ok(str(s))


@pixel_app.command("gif")
def px_gif(quadros: List[Path] = typer.Argument(None, help="quadros em ordem (ou use --sheet)"),
           sheet: Optional[Path] = typer.Option(None, help="spritesheet para fatiar"),
           largura: int = typer.Option(0, help="largura do quadro (com --sheet)"), altura: int = typer.Option(0, help="altura do quadro (com --sheet)"),
           duracao: int = typer.Option(100, help="ms por quadro"), fator: int = typer.Option(1, help="ampliação inteira"),
           saida: Path = typer.Option(Path("animacao.gif"), "-o", "--saida", help="arquivo de saída")):
    """GIF animado a partir de quadros, spritesheet ou .aseprite."""
    from . import pixel as X

    if sheet:
        fs = X.ler_ase(sheet)["quadros"] if sheet.suffix.lower() in X.EXT_ASE else X.fatiar(X.abrir(sheet), largura, altura)
    else:
        fs = [X.abrir(q) for q in quadros or []]
    if not fs:
        raise typer.BadParameter("nenhum quadro")
    X.gif(fs, saida, duracao, fator)
    _ok(f"{saida} ({len(fs)} quadros)")


@pixel_app.command("referencias")
def px_ref(tema: str):
    """Pesquisa na web tutoriais e referências de pixel art/Aseprite."""
    from ..i18n import idioma_atual
    from ..web.busca import PesquisaWeb
    from .pixel import consultas_referencia

    web = PesquisaWeb(_cfg())
    vistos = set()
    for q in consultas_referencia(tema, idioma_atual()):
        for r in web.buscar(q):
            if r.url not in vistos:
                vistos.add(r.url)
                _c().print(f"• [bold]{escape(r.titulo)}[/]\n  {escape(r.url)}", highlight=False)


@sheet_app.command("montar")
def sh_montar(quadros: List[Path], colunas: int = typer.Option(0, help="0 = automático"),
              espaco: int = typer.Option(0, help="px entre quadros"), duracao: int = typer.Option(100, help="ms por quadro"),
              saida: Path = typer.Option(Path("sheet.png"), "-o", "--saida", help="arquivo de saída")):
    """Monta spritesheet + JSON (formato do Aseprite: Godot/Unity/Phaser leem)."""
    from . import pixel as X

    folha, meta = X.montar([X.abrir(q) for q in quadros], colunas, espaco, [q.stem for q in quadros], duracao)
    meta["meta"]["image"] = saida.name
    saida.parent.mkdir(parents=True, exist_ok=True)
    folha.save(saida)
    saida.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    _ok(f"{saida} + {saida.with_suffix('.json').name} ({folha.width}x{folha.height})")


@sheet_app.command("fatiar")
def sh_fatiar(sheet: Path, largura: int = typer.Option(..., help="largura do quadro"), altura: int = typer.Option(..., help="altura do quadro"),
              margem: int = typer.Option(0, help="px"), espaco: int = typer.Option(0, help="px entre quadros"),
              saida: Path = typer.Option(Path("quadros"), "-o", "--saida", help="pasta de saída")):
    """Fatia uma spritesheet em PNGs (pula quadros vazios)."""
    from . import pixel as X

    fs = X.fatiar(X.abrir(sheet), largura, altura, margem, espaco)
    saida.mkdir(parents=True, exist_ok=True)
    for i, q in enumerate(fs):
        q.save(saida / f"{sheet.stem}_{i:03d}.png")
    _ok(f"{len(fs)} quadro(s) em {saida}")


def _ase():
    from .pixel import Aseprite, detectar_aseprite

    return Aseprite(detectar_aseprite(_cfg().kits.pixel.aseprite))


@ase_app.command("info")
def ase_info():
    """Mostra se o Aseprite foi encontrado (e onde procurar)."""
    from .pixel import caminhos_aseprite

    a = _ase()
    if a.disponivel:
        _ok(f"Aseprite: {a.exe} — {a.versao()}")
    else:
        _c().print("[yellow]Aseprite não encontrado.[/] Configure [bold]kits.pixel.aseprite[/] ou a variável ASEPRITE. "
                   "Sem ele, exportações usam o leitor .aseprite embutido.\nProcurei em:")
        for p in caminhos_aseprite()[:8]:
            _c().print(f"  {p}", highlight=False)


@ase_app.command("exportar")
def ase_exportar(arquivo: Path, saida: Optional[Path] = typer.Option(None, "-o", "--saida", help="arquivo de saída"),
                 escala: int = typer.Option(1, help="escala inteira"), tag: str = typer.Option("", help="só esta tag de animação"),
                 camada: str = typer.Option("", help="só esta camada (precisa do Aseprite)")):
    """Exporta .ase/.aseprite em PNG (um por quadro)."""
    s = _ase().exportar_png(arquivo, saida or arquivo.with_suffix(".png"), escala, camada, tag)
    _ok(f"{len(s)} PNG(s): " + ", ".join(str(x) for x in s[:6]))


@ase_app.command("sheet")
def ase_sheet(arquivo: Path, saida: Optional[Path] = typer.Option(None, "-o", "--saida", help="arquivo de saída"),
              tipo: str = typer.Option("horizontal", help="horizontal | vertical | rows | columns | packed"),
              escala: int = typer.Option(1, help="escala inteira"), tag: str = typer.Option("", help="só esta tag de animação")):
    """Exporta spritesheet + JSON de um .aseprite."""
    a = _ase()
    png, js = a.exportar_sheet(arquivo, saida or arquivo.with_suffix(".sheet.png"), tipo=tipo, escala=escala, tag=tag)
    _ok(f"{png} + {js}" + ("" if a.disponivel else " (leitor embutido)"))


@ase_app.command("script")
def ase_script(script: Path, arquivo: Optional[Path] = typer.Option(None, help=".aseprite a abrir antes"),
               param: List[str] = typer.Option([], "--param", "-p", help="chave=valor (repita)")):
    """Roda um script Lua no Aseprite (--batch --script)."""
    out = _ase().rodar_script(script, dict(p.split("=", 1) for p in param if "=" in p), arquivo)
    _c().print(out or "ok", highlight=False)


@ase_app.command("scripts-lua")
def ase_scripts(pasta: Path = typer.Option(Path("scripts_aseprite"), help="onde salvar")):
    """Salva os scripts Lua prontos (aplicar paleta, exportar camadas, redimensionar)."""
    from .pixel import salvar_scripts_lua

    for p in salvar_scripts_lua(pasta):
        _ok(str(p))


# ------------------------------------------------------------------ ABNT
@abnt_app.command("ref")
def abnt_ref(identificadores: List[str] = typer.Argument(..., help="DOI, ISBN ou URL (vários)"),
             como_json: bool = typer.Option(False, "--json", help="mostra os metadados em JSON")):
    """Referências NBR 6023 a partir de DOI, ISBN ou URL (em ordem alfabética)."""
    from . import abnt as A

    refs = []
    for i in identificadores:
        try:
            refs.append(A.identificar(i))
        except Exception as e:  # noqa: BLE001
            _c().print(f"[red]✗ {escape(i)}: {escape(str(e))}[/]")
    A.desambiguar_anos(refs)
    norma = _cfg().kits.abnt.norma_citacao
    for r in sorted(refs, key=A.chave_ordenacao):
        _c().print(A.formatar_referencia(r).replace("**", ""), highlight=False)
        _c().print(f"  [dim]citação: {A.citacao(r, norma=norma)} · narrativa: {A.citacao(r, narrativa=True, norma=norma)}[/]",
                   highlight=False)
        if r.avisos:
            _c().print(f"  [yellow]confira: {'; '.join(r.avisos)}[/]")
        if como_json:
            _c().print_json(json.dumps(r.dict(), ensure_ascii=False))


@abnt_app.command("citar")
def abnt_citar(identificador: str, pagina: str = typer.Option("", help="página(s)"),
               narrativa: bool = typer.Option(False, help="Silva (2020) em vez de (Silva, 2020)")):
    """Citação autor-data (NBR 10520)."""
    from . import abnt as A

    _c().print(A.citacao(A.identificar(identificador), pagina, narrativa, _cfg().kits.abnt.norma_citacao), highlight=False)


@abnt_app.command("arquivo")
def abnt_arquivo(caminho: Path):
    """Referência de um arquivo da biblioteca (DOI/ISBN no texto ou metadados do PDF/DOCX)."""
    from . import abnt as A

    r = A.de_arquivo(caminho)
    _c().print(A.formatar_referencia(r).replace("**", ""), highlight=False)
    if r.avisos:
        _c().print(f"[yellow]confira: {'; '.join(r.avisos)}[/]")


@abnt_app.command("documento")
def abnt_doc(texto: Path = typer.Argument(..., help="markdown com # títulos (citações no formato (Autor, ano))"),
             titulo: str = typer.Option(..., help="título do trabalho"), autor: str = typer.Option("", help="nome do autor"),
             subtitulo: str = typer.Option("", help="subtítulo"), instituicao: str = typer.Option("", help="instituição"),
             curso: str = typer.Option("", help="curso"), local: str = typer.Option("", help="cidade"), ano: str = typer.Option("", help="ano"),
             natureza: str = typer.Option("", help="ex.: Trabalho de Conclusão de Curso apresentado ..."),
             orientador: str = typer.Option("", help="orientador(a)"),
             fonte: str = typer.Option("", help="Times New Roman | Arial"),
             ref: List[str] = typer.Option([], "--ref", help="DOI/ISBN/URL de uma obra citada (repita)"),
             saida: Path = typer.Option(Path("trabalho-abnt.docx"), "-o", "--saida", help="arquivo de saída")):
    """Gera .docx NBR 14724 (capa, folha de rosto, sumário, texto, referências)."""
    from . import abnt as A

    k = _cfg().kits.abnt
    refs = []
    for i in ref:
        try:
            refs.append(A.identificar(i))
        except Exception as e:  # noqa: BLE001
            _c().print(f"[red]✗ {escape(i)}: {escape(str(e))}[/]")
    t = A.Trabalho(titulo=titulo, subtitulo=subtitulo, autor=autor or k.autor or "Autor", instituicao=instituicao or k.instituicao,
                   curso=curso or k.curso, local=local or k.local, ano=ano, natureza=natureza, orientador=orientador,
                   fonte=fonte or k.fonte)
    _ok(str(A.gerar_docx(t, texto.read_text(encoding="utf-8"), refs, saida)) + f" ({len(refs)} referência(s))")


# ------------------------------------------------------------------ kits (ligar/desligar)
def salvar_kits(cfg) -> Path:
    """Atualiza só o bloco `kits:` do config.yaml (preserva comentários do resto)."""
    import yaml

    alvo = Path(cfg.caminho_arquivo or "config.yaml")
    bloco = yaml.safe_dump({"kits": cfg.kits.model_dump()}, allow_unicode=True, sort_keys=False).rstrip().splitlines()
    linhas = alvo.read_text(encoding="utf-8").splitlines() if alvo.exists() else []
    if "kits:" in linhas:
        i = linhas.index("kits:")
        j = i + 1
        while j < len(linhas) and (linhas[j].startswith((" ", "#")) or not linhas[j].strip()):
            j += 1
        linhas = linhas[:i] + bloco + linhas[j:]
    else:
        linhas += ["", "# Kits opcionais (v0.6): pixel art e ABNT"] + bloco
    alvo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return alvo


def kits_cmd(ativar: List[str] = typer.Option([], "--ativar", help="pixel | abnt"),
             desativar: List[str] = typer.Option([], "--desativar", help="pixel | abnt")):
    """Mostra, ativa ou desativa os kits (pixel, abnt) para o agente e a interface."""
    from .pixel import detectar_aseprite

    cfg = _cfg()
    for k in ativar:
        getattr(cfg.kits, k).ativo = True
    for k in desativar:
        getattr(cfg.kits, k).ativo = False
    if ativar or desativar:
        _ok(f"salvo em {salvar_kits(cfg)}")
    t = Table()
    for c in ("kit", "ativo", "detalhe"):
        t.add_column(c)
    ase = detectar_aseprite(cfg.kits.pixel.aseprite)
    t.add_row("pixel", "✓" if cfg.kits.pixel.ativo else "—", f"Aseprite: {ase or 'não encontrado (fallback embutido)'}")
    t.add_row("abnt", "✓" if cfg.kits.abnt.ativo else "—", f"citações NBR 10520:{cfg.kits.abnt.norma_citacao}, fonte {cfg.kits.abnt.fonte}")
    _c().print(t)
