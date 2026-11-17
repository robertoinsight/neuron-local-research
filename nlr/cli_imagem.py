"""`nlr imagem ...`: análise de imagens com modelo de visão e pesquisa na internet pela imagem (v0.7)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.markup import escape

imagem_app = typer.Typer(help="Imagens: análise com modelo de visão e pesquisa na internet pela imagem.",
                         no_args_is_help=True)


def _base():
    from . import cli

    return cli


def _imprimir_streaming():
    from . import cli

    def receber(p: str) -> None:
        cli.console.print(p, end="", markup=False, highlight=False, soft_wrap=True)

    return receber


@imagem_app.command("analisar")
def analisar(caminho: Path = typer.Argument(..., help="arquivo de imagem (png, jpg, webp, gif, bmp, tiff)"),
             modo: str = typer.Option("", "--modo", "-m", help="minucioso | geral | texto | pixel (padrão: config visao.modo_padrao)"),
             pergunta: str = typer.Option("", "--pergunta", "-p", help="pergunta específica sobre a imagem"),
             salvar: Optional[Path] = typer.Option(None, "--salvar", help="salva a análise em Markdown neste arquivo")):
    """Analisa uma imagem com o modelo de visão (minuciosa, texto, pixel art)."""
    from .erros import AgenteErro
    from .ferramentas import visao
    from .llm.cliente import ClienteLLM

    cli = _base()
    cfg = cli._cfg()
    llm = ClienteLLM(cfg, eventos=lambda m: cli._eventos("aviso", m))
    try:
        r = visao.analisar(llm, cfg, [caminho.expanduser().resolve()], modo, pergunta,
                           ao_receber=_imprimir_streaming(), eventos=cli._eventos)
    except AgenteErro as e:
        cli._erro(e)
        return
    cli.console.print()
    cli.console.print(f"[dim]{escape(r.info)} · {r.modo} · {r.vistas} vista(s) · {escape(r.modelo)}[/]")
    if salvar:
        salvar.write_text(f"# Análise de {caminho.name}\n\n_{r.info} · {r.modo} · {r.modelo}_\n\n{r.texto}\n", encoding="utf-8")
        cli.console.print(f"[green]Salvo em {escape(str(salvar))}[/]")


@imagem_app.command("pesquisar")
def pesquisar(caminho: Path = typer.Argument(..., help="arquivo de imagem (png, jpg, webp, gif, bmp, tiff)"),
              foco: str = typer.Option("", "--foco", "-f", help="o que você quer descobrir (ex.: 'que planta é essa')"),
              salvar: Optional[Path] = typer.Option(None, "--salvar", help="salva o resultado em Markdown neste arquivo")):
    """Identifica o conteúdo da imagem e pesquisa na internet, com fontes numeradas."""
    from .erros import AgenteErro
    from .ferramentas import visao
    from .llm.cliente import ClienteLLM
    from .web.busca import PesquisaWeb

    cli = _base()
    cfg = cli._cfg()
    llm = ClienteLLM(cfg, eventos=lambda m: cli._eventos("aviso", m))
    try:
        r = visao.pesquisar(llm, cfg, PesquisaWeb(cfg), caminho.expanduser().resolve(), foco,
                            ao_receber=_imprimir_streaming(), eventos=cli._eventos)
    except AgenteErro as e:
        cli._erro(e)
        return
    cli.console.print()
    if r.fontes:
        cli.console.print("\n[bold]Fontes[/]")
        for f in r.fontes:
            cli.console.print(f"  {escape(f.cabecalho())}", highlight=False)
    for a in r.avisos:
        cli.console.print(f"[yellow]Aviso: {escape(a)}[/]")
    if salvar:
        refs = "\n".join(f"- {f.cabecalho()}" for f in r.fontes)
        salvar.write_text(f"# Pesquisa pela imagem {caminho.name}\n\n{r.texto}\n\n## Fontes\n{refs}\n", encoding="utf-8")
        cli.console.print(f"[green]Salvo em {escape(str(salvar))}[/]")


@imagem_app.command("status")
def status():
    """Mostra qual modelo vai analisar as imagens, se ele tem visão e se está carregado."""
    from rich.table import Table

    from .ferramentas import visao
    from .llm.cliente import ClienteLLM

    cli = _base()
    cfg = cli._cfg()
    llm = ClienteLLM(cfg)
    est = visao.estado_visao(llm, cfg)
    sim = {True: "[green]sim[/]", False: "[red]não[/]", None: "[yellow]?[/]"}
    tab = Table(show_header=False)
    tab.add_row("Servidor", escape(est.backend))
    tab.add_row("Modelo de visão", escape(est.modelo or "-") + f" [dim]({est.origem or '-'})[/]")
    tab.add_row("Tem visão 👁", sim[est.tem_visao])
    tab.add_row("Carregado", sim[est.carregado])
    tab.add_row("Com visão no servidor", escape(", ".join(m["id"] + (" ●" if m["carregado"] else "") for m in est.modelos_visao) or "(nenhum)"))
    br = cfg.visao.busca_reversa
    tab.add_row("Busca reversa", escape(f"{br.provedor}" + (" (com consentimento)" if br.consentimento_envio else "")))
    cli.console.print(tab)
    for a in est.avisos:
        cli.console.print(f"[yellow]Aviso: {escape(a)}[/]")
    if est.erro:
        cli.console.print(f"[bold red]{escape(est.erro)}[/]")
        raise typer.Exit(1)
    cli.console.print("[green]Pronto para analisar imagens.[/]")
