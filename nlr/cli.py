"""Linha de comando: `agente ...` (digite `agente --help`)."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from . import __version__
from .config import Config, carregar
from .erros import AgenteErro

for _s in (sys.stdout, sys.stderr):  # Windows: evita erro de acentuação no terminal
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

console = Console()
app = typer.Typer(help="Neuron Local Research — agente autônomo, persistente e local-first.", no_args_is_help=True,
                  add_completion=False, rich_markup_mode="rich")
projeto_app = typer.Typer(help="Projetos autônomos (planejar, executar, revisar, retomar).", no_args_is_help=True)
bib_app = typer.Typer(help="Biblioteca de arquivos (pastas, status, busca).", no_args_is_help=True)
mem_app = typer.Typer(help="Memória de longo prazo.", no_args_is_help=True)
cfg_app = typer.Typer(help="Configuração (config.yaml).", no_args_is_help=True)
app.add_typer(projeto_app, name="projeto")
app.add_typer(bib_app, name="biblioteca")
app.add_typer(mem_app, name="memoria")
app.add_typer(cfg_app, name="config")
from .kits.cli import abnt_app, kits_cmd, pixel_app  # noqa: E402

app.add_typer(pixel_app, name="pixel")
app.add_typer(abnt_app, name="abnt")
app.command("kits")(kits_cmd)
from .cli_imagem import imagem_app  # noqa: E402

app.add_typer(imagem_app, name="imagem")

ESTADO = {"config": None, "verbose": False, "idioma": None}
CORES = {"fase": "bold cyan", "tarefa": "bold magenta", "revisao": "yellow", "ferramenta": "blue", "comando": "bold blue",
         "status": "dim", "aviso": "bold yellow", "erro": "bold red", "pensamento": "dim italic", "observacao": "dim",
         "rota": "dim"}


def _cfg() -> Config:
    from .i18n import definir_idioma, iniciar

    try:
        cfg = carregar(ESTADO["config"])
        if ESTADO["idioma"]:
            cfg.idioma = definir_idioma(ESTADO["idioma"])
        else:
            cfg.idioma = iniciar(cfg)
        return cfg
    except AgenteErro as e:
        console.print(f"[bold red]{escape(str(e))}[/]")
        raise typer.Exit(2)


def _eventos(tipo: str, msg: str) -> None:
    if tipo in ("pensamento", "observacao") and not ESTADO["verbose"]:
        return
    if tipo == "rota":
        console.print(f"[dim]→ modo: {escape(msg)}[/]")
        return
    msg = msg if len(msg) < 400 or ESTADO["verbose"] else msg[:400] + "..."
    console.print(f"[{CORES.get(tipo, 'white')}]• {tipo}: {escape(msg)}[/]", highlight=False)


def _confirmar(titulo: str, detalhe: str) -> bool:
    if not sys.stdin.isatty():
        console.print(f"[yellow]{escape(titulo)} (negado: terminal não interativo)[/]\n{escape(detalhe)}")
        return False
    console.print(Panel(detalhe, title=titulo, border_style="yellow"))
    return Confirm.ask("Autorizar?", default=False)


def _servicos(cfg: Config, mcp: bool = False):
    from .servicos import Servicos

    return Servicos(cfg, eventos=_eventos, confirmar=_confirmar, usar_mcp=mcp)


def _erro(e: Exception) -> None:
    console.print(f"[bold red]Erro:[/] {escape(str(e))}")
    raise typer.Exit(1)


@app.callback()
def principal(config: Optional[str] = typer.Option(None, "--config", "-c", help="caminho do config.yaml"),
              verbose: bool = typer.Option(False, "--verbose", "-v", help="mostra pensamentos e observações"),
              idioma: Optional[str] = typer.Option(None, "--idioma", "-l", help="pt | en (padrão: config.yaml)")):
    ESTADO["config"] = config
    ESTADO["idioma"] = idioma
    ESTADO["verbose"] = verbose
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


@app.command()
def versao():
    """Mostra a versão."""
    console.print(f"Neuron Local Research {__version__}")


# ------------------------------------------------------------------ chat
AJUDA_CHAT = """Comandos do chat:
  /web <pergunta>         pesquisa na internet        /biblioteca <pergunta>  pesquisa nos seus documentos
  /ambos <pergunta>       cruza biblioteca + web      /agente <tarefa>        agente com ferramentas (arquivos, comandos)
  /projeto <objetivo>     cria e executa um projeto   /lembrar <fato>         guarda na memória
  /memoria [busca]        mostra lembranças           /nova                   nova conversa
  /ajuda                  esta ajuda                  /sair                   sair"""


@app.command()
def chat(sessao: Optional[str] = typer.Option(None, help="id da sessão para continuar"),
         continuar: bool = typer.Option(False, "--continuar", help="continua a última conversa"),
         modo: str = typer.Option("auto", help="auto | conversa | biblioteca | web | ambos | agente"),
         mcp: bool = typer.Option(True, help="conecta os servidores MCP configurados")):
    """Conversa interativa com memória (Ctrl+C ou /sair para sair)."""
    from .agentes.chat import SessaoChat

    cfg = _cfg()
    serv = _servicos(cfg, mcp=mcp)
    sid = sessao or (serv.memoria.ultima_sessao() if continuar else None)
    s = SessaoChat(serv, sid, eventos=_eventos, confirmar=_confirmar)
    console.print(Panel(f"Neuron Local Research {__version__} — modelo: [bold]{cfg.modelo.modelo_chat}[/] ({cfg.modelo.backend})\n"
                        f"Sessão: {s.id}   |   /ajuda para comandos", border_style="cyan"))
    try:
        while True:
            try:
                msg = console.input("[bold green]Você> [/]").strip()
            except EOFError:
                break
            if not msg:
                continue
            m_modo = modo
            if msg.startswith("/"):
                cmd, _, resto = msg.partition(" ")
                cmd = cmd.lower()
                if cmd in ("/sair", "/exit", "/quit"):
                    break
                if cmd == "/ajuda":
                    console.print(AJUDA_CHAT)
                    continue
                if cmd == "/nova":
                    s.extrair_memorias()
                    s = SessaoChat(serv, None, eventos=_eventos, confirmar=_confirmar)
                    console.print(f"[dim]Nova sessão: {s.id}[/]")
                    continue
                if cmd == "/lembrar":
                    lid = serv.memoria.lembrar(resto, "fato", "global", origem="usuario")
                    console.print(f"[green]Memorizado (id {lid}).[/]")
                    continue
                if cmd == "/memoria":
                    itens = serv.memoria.recordar(resto, ["global"], k=10) if resto else serv.memoria.listar("global", 15)
                    for i in itens:
                        console.print(f"  [{i.id}] ({i.tipo}) {i.texto}", markup=False)
                    if not itens:
                        console.print("  (vazia)")
                    continue
                if cmd == "/projeto":
                    _rodar_projeto(serv, resto, None)
                    continue
                if cmd in ("/web", "/biblioteca", "/ambos", "/agente", "/conversa"):
                    m_modo = cmd[1:]
                    msg = resto
                else:
                    console.print("Comando desconhecido. /ajuda")
                    continue
            console.print("[bold cyan]Agente>[/] ", end="")
            try:
                r = s.responder(msg, m_modo, ao_receber=lambda t: console.print(t, end="", highlight=False, markup=False))
                console.print()
                for a in r.avisos:
                    console.print(f"[yellow]Aviso: {escape(a)}[/]")
            except AgenteErro as e:
                console.print(f"\n[bold red]{escape(str(e))}[/]")
    except KeyboardInterrupt:
        console.print()
    finally:
        try:
            s.extrair_memorias()
        except Exception:  # noqa: BLE001
            pass
        serv.fechar()
        console.print("[dim]Até logo! A conversa ficou salva; continue com: nlr chat --continuar[/]")


@app.command()
def perguntar(pergunta: str, modo: str = typer.Option("auto", help="auto | conversa | biblioteca | web | ambos | agente")):
    """Pergunta única (sem modo interativo). Útil em scripts."""
    from .agentes.chat import SessaoChat

    cfg = _cfg()
    serv = _servicos(cfg)
    try:
        s = SessaoChat(serv, None, eventos=_eventos, confirmar=_confirmar)
        r = s.responder(pergunta, modo)
        console.print(Markdown(r.texto))
        for a in r.avisos:
            console.print(f"[yellow]Aviso: {escape(a)}[/]")
    except AgenteErro as e:
        _erro(e)
    finally:
        serv.fechar()


@app.command()
def pesquisar(pergunta: str,
              fontes: str = typer.Option("ambos", help="biblioteca | web | ambos"),
              salvar: Optional[Path] = typer.Option(None, help="salva o relatório em Markdown neste arquivo"),
              profunda: bool = typer.Option(False, "--profunda", help="várias rodadas: plano, lacunas, relatório longo"),
              profundidade: int = typer.Option(0, help="rodadas (0 = pelo perfil do modelo)"),
              largura: int = typer.Option(0, help="subperguntas por rodada (0 = pelo perfil)"),
              formatos: str = typer.Option("", help="md,docx,pdf,abnt (padrão: config profunda.formatos)")):
    """Pesquisa com citações na biblioteca e/ou na web. --profunda = pesquisa profunda com relatório salvo."""
    from .agentes.pesquisa import pesquisar as _pesq, relatorio_markdown

    cfg = _cfg()
    if formatos:
        cfg.profunda.formatos = [f.strip() for f in formatos.split(",") if f.strip()]
    serv = _servicos(cfg)
    try:
        ctx = serv.contexto(cfg.dir_dados / "area_de_trabalho")
        if profunda:
            from .agentes.profunda import PesquisaProfunda

            def prog(d):
                console.print(f"[cyan]• {d['etapa']}[/] {escape(str(d.get('msg', ''))[:160])}", highlight=False)

            rel = PesquisaProfunda(ctx, prog).executar(pergunta, profundidade, largura,
                                                       usar_web=fontes in ("web", "ambos"),
                                                       usar_biblioteca=fontes in ("biblioteca", "ambos"))
            console.print(Markdown(rel.markdown))
            if salvar:
                salvar.write_text(rel.markdown, encoding="utf-8")
                rel.arquivos.append(str(salvar))
            console.print(f"[green]{escape(', '.join(rel.arquivos))}[/]")
            return
        r = _pesq(ctx, pergunta, usar_biblioteca=fontes in ("biblioteca", "ambos"), usar_web=fontes in ("web", "ambos"),
                  ao_receber=lambda t: console.print(t, end="", highlight=False, markup=False))
        console.print("\n\n[bold]Fontes[/]")
        for f in r.fontes:
            console.print(f"  {f.cabecalho()}", highlight=False, markup=False)
        for a in r.avisos:
            console.print(f"[yellow]Aviso: {escape(a)}[/]")
        if salvar:
            salvar.write_text(relatorio_markdown(pergunta, r), encoding="utf-8")
            console.print(f"[green]Relatório salvo em {salvar}[/]")
    except AgenteErro as e:
        _erro(e)
    finally:
        serv.fechar()


# ------------------------------------------------------------------ projetos
def _rodar_projeto(serv, objetivo: str, nome: Optional[str]):
    from .agentes.projeto import ExecutorProjeto

    if not objetivo.strip():
        console.print("[red]Diga o objetivo do projeto.[/]")
        return None
    ex = ExecutorProjeto(serv, eventos=_eventos, confirmar=_confirmar)
    try:
        info = ex.novo(objetivo, nome)
        _mostrar_status(serv.cfg, info.id)
        return info
    except KeyboardInterrupt:
        console.print("[yellow]Interrompido. O progresso está salvo.[/]")
    except AgenteErro as e:
        console.print(f"[bold red]{escape(str(e))}[/]")
    finally:
        ex.fechar()
    return None


@projeto_app.command("novo")
def projeto_novo(objetivo: str, nome: Optional[str] = typer.Option(None, help="nome curto do projeto"),
                 autonomo: bool = typer.Option(False, "--autonomo", help="liga o modo autônomo SÓ nesta execução"),
                 mcp: bool = typer.Option(True, help="conecta os servidores MCP configurados")):
    """Cria um projeto e executa: pesquisa -> plano -> tarefas -> revisão -> relatório."""
    cfg = _cfg()
    if autonomo:
        cfg.seguranca.modo_autonomo = True
        console.print("[bold yellow]Modo autônomo LIGADO nesta execução: comandos da lista de permitidos rodam sem perguntar.[/]")
    serv = _servicos(cfg, mcp=mcp)
    try:
        info = _rodar_projeto(serv, objetivo, nome)
        if info is None:
            raise typer.Exit(1)
    finally:
        serv.fechar()


@projeto_app.command("retomar")
def projeto_retomar(projeto_id: str, autonomo: bool = typer.Option(False, "--autonomo"),
                    mcp: bool = typer.Option(True)):
    """Retoma um projeto interrompido do ponto em que parou."""
    from .agentes.projeto import ExecutorProjeto

    cfg = _cfg()
    if autonomo:
        cfg.seguranca.modo_autonomo = True
    serv = _servicos(cfg, mcp=mcp)
    ex = ExecutorProjeto(serv, eventos=_eventos, confirmar=_confirmar)
    try:
        info = ex.retomar(projeto_id)
        _mostrar_status(cfg, info.id)
    except KeyboardInterrupt:
        console.print("[yellow]Interrompido. O progresso está salvo.[/]")
    except AgenteErro as e:
        _erro(e)
    finally:
        ex.fechar()
        serv.fechar()


@projeto_app.command("continuar")
def projeto_continuar(projeto_id: str, pedido: str, autonomo: bool = typer.Option(False, "--autonomo")):
    """Pede mais trabalho num projeto existente (novo ciclo de plano/execução na mesma pasta)."""
    from .agentes.projeto import ExecutorProjeto

    cfg = _cfg()
    if autonomo:
        cfg.seguranca.modo_autonomo = True
    serv = _servicos(cfg, mcp=True)
    ex = ExecutorProjeto(serv, eventos=_eventos, confirmar=_confirmar)
    try:
        info = ex.continuar(projeto_id, pedido)
        _mostrar_status(cfg, info.id)
    except AgenteErro as e:
        _erro(e)
    finally:
        ex.fechar()
        serv.fechar()


@projeto_app.command("listar")
def projeto_listar():
    """Lista os projetos."""
    from datetime import datetime

    from .agentes.projeto_store import ProjetoStore

    cfg = _cfg()
    t = Table(title=f"Projetos em {cfg.dir_projetos}")
    for c in ("id", "status", "fase", "atualizado", "objetivo"):
        t.add_column(c)
    for p in ProjetoStore(cfg).listar():
        t.add_row(p.id, p.status, p.fase, datetime.fromtimestamp(p.atualizado).strftime("%d/%m %H:%M"), escape(p.objetivo[:60]))
    console.print(t)


def _mostrar_status(cfg: Config, pid: str) -> None:
    from .agentes.projeto_store import STATUS_ICONE, ProjetoStore

    st = ProjetoStore(cfg)
    info = st.carregar(pid)
    resumo, tarefas = st.carregar_tarefas(info)
    console.print(Panel(f"[bold]{escape(info.nome)}[/]\nid: {info.id}\nstatus: {info.status}  fase: {info.fase}\n"
                        f"pasta: {info.pasta}" + (f"\n[red]erro: {escape(info.erro)}[/]" if info.erro else ""),
                        title="Projeto", border_style="cyan"))
    for tt in tarefas:
        console.print(f"  {STATUS_ICONE.get(tt['status'], '?')} {tt['id']}. {tt['titulo']} ({tt['tipo']})", highlight=False, markup=False)


@projeto_app.command("status")
def projeto_status(projeto_id: str):
    """Mostra o status e as tarefas de um projeto."""
    try:
        _mostrar_status(_cfg(), projeto_id)
    except AgenteErro as e:
        _erro(e)


# ------------------------------------------------------------------ biblioteca
@app.command()
def indexar(forcar: bool = typer.Option(False, "--forcar", help="reprocessa tudo"),
            vetores: bool = typer.Option(False, "--vetores", help="só completa vetores que faltam"),
            pasta: Optional[List[Path]] = typer.Option(None, help="indexa só esta pasta (pode repetir)")):
    """Indexa (incrementalmente) as pastas da biblioteca."""
    cfg = _cfg()
    serv = _servicos(cfg)
    try:
        if vetores:
            n = serv.indice.completar_vetores(progresso=lambda s: console.print(f"[dim]{escape(s)}[/]"))
            console.print(f"[green]{n} vetor(es) calculado(s).[/]")
            return
        rel = serv.indice.indexar([p.resolve() for p in pasta] if pasta else None, forcar=forcar,
                                  progresso=lambda s: console.print(f"[dim]{escape(s)}[/]", highlight=False))
        console.print(f"[green]{rel.resumo()}[/]")
        for arq, err in rel.erros[:20]:
            console.print(f"  [red]erro[/] {escape(str(arq))}: {escape(str(err))}", highlight=False)
        if rel.aviso_embeddings:
            console.print(f"[yellow]Embeddings indisponíveis: {escape(rel.aviso_embeddings.splitlines()[0])}\n"
                          "Depois de resolver, rode: nlr indexar --vetores[/]")
    except AgenteErro as e:
        _erro(e)
    finally:
        serv.fechar()


@bib_app.command("adicionar")
def bib_adicionar(pasta: Path):
    """Adiciona uma pasta à biblioteca (salva no config.yaml)."""
    cfg = _cfg()
    p = pasta.expanduser().resolve()
    if not p.exists():
        _erro(AgenteErro(f"A pasta não existe: {p}"))
    if str(p) not in cfg.biblioteca.pastas:
        cfg.biblioteca.pastas.append(str(p))
    _salvar_cfg(cfg)
    console.print(f"[green]Pasta adicionada: {p}[/]\nAgora rode: nlr indexar")


@bib_app.command("remover")
def bib_remover(pasta: Path):
    """Remove uma pasta da biblioteca (os trechos somem na próxima indexação)."""
    cfg = _cfg()
    alvo = str(pasta.expanduser().resolve())
    cfg.biblioteca.pastas = [x for x in cfg.biblioteca.pastas if str(cfg.resolver(x)) != alvo and x != str(pasta)]
    _salvar_cfg(cfg)
    console.print("[green]Removida. Rode 'nlr indexar' para limpar o índice.[/]")


@bib_app.command("documentos")
def bib_documentos():
    """Mostra os documentos indexados: trechos, tabelas, páginas com OCR e avisos."""
    from .biblioteca import documentos as D
    from .biblioteca.indice import IndiceBiblioteca

    cfg = _cfg()
    console.print(f"OCR: {D.motor_ocr(cfg.biblioteca.ocr) or '(não instalado: pip install rapidocr-onnxruntime)'}  |  "
                  f"reranker: {cfg.biblioteca.reranker}", highlight=False)
    t = Table()
    for c in ("arquivo", "trechos", "tabelas", "OCR", "avisos"):
        t.add_column(c)
    for a in IndiceBiblioteca(cfg).arquivos():
        t.add_row(escape(a["nome"]), str(a["trechos"]), str(a["tabelas"]), str(a["paginas_ocr"] or "-"),
                  escape(a["erro"] or a["avisos"] or ""))
    console.print(t)


@bib_app.command("status")
def bib_status():
    """Mostra o estado do índice."""
    from .biblioteca.indice import IndiceBiblioteca

    cfg = _cfg()
    st = IndiceBiblioteca(cfg).status()
    console.print(f"Pastas: {', '.join(cfg.biblioteca.pastas) or '(nenhuma)'}")
    console.print(f"Arquivos: {st['arquivos']}  |  trechos: {st['trechos']}  |  com vetor: {st['trechos_com_vetor']}  "
                  f"|  embeddings: {st['embedder']}\nÍndice: {st['db']}")
    for c, e in st["erros"]:
        console.print(f"  [red]erro[/] {escape(str(c))}: {escape(str(e))}", highlight=False)


@bib_app.command("buscar")
def bib_buscar(consulta: str, k: int = typer.Option(6)):
    """Busca trechos na biblioteca (sem usar o modelo de chat)."""
    from .biblioteca.busca import buscar

    cfg = _cfg()
    serv = _servicos(cfg)
    try:
        for i, r in enumerate(buscar(serv.indice, consulta, k=k), start=1):
            console.print(Panel(r.texto[:700], title=f"[{i}] {r.rotulo}", border_style="green"), highlight=False)
    finally:
        serv.fechar()


# ------------------------------------------------------------------ memória
@mem_app.command("listar")
def mem_listar(escopo: Optional[str] = typer.Option(None, help="global ou projeto:<id>")):
    """Lista as lembranças."""
    from .memoria.armazenamento import Memoria

    m = Memoria(_cfg())
    t = Table()
    for c in ("id", "escopo", "tipo", "origem", "usos", "texto"):
        t.add_column(c)
    for i in m.listar(escopo):
        t.add_row(str(i.id), i.escopo, i.tipo, i.rotulo(), str(i.usos), ("📌 " if i.fixada else "") + escape(i.texto))
    console.print(t)


@mem_app.command("adicionar")
def mem_adicionar(texto: str, tipo: str = typer.Option("fato", help="fato | preferencia | decisao | licao"),
                  escopo: str = typer.Option("global")):
    """Guarda uma lembrança manualmente."""
    cfg = _cfg()
    serv = _servicos(cfg)
    try:
        console.print(f"[green]Memorizado (id {serv.memoria.lembrar(texto, tipo, escopo, origem='usuario')}).[/]")
    finally:
        serv.fechar()


@mem_app.command("buscar")
def mem_buscar(consulta: str):
    """Procura nas lembranças."""
    cfg = _cfg()
    serv = _servicos(cfg)
    try:
        escopos = ["global"] + [f"projeto:{p.name}" for p in cfg.dir_projetos.iterdir() if p.is_dir()]
        for i in serv.memoria.recordar(consulta, escopos, k=10):
            console.print(f"[{i.id}] ({i.tipo}, {i.escopo}) {i.rotulo()} {i.texto}", highlight=False, markup=False)
    finally:
        serv.fechar()


@mem_app.command("esquecer")
def mem_esquecer(id_lembranca: int):
    """Apaga uma lembrança pelo id."""
    from .memoria.armazenamento import Memoria

    ok = Memoria(_cfg()).esquecer(id_lembranca)
    console.print("[green]Apagada.[/]" if ok else "[yellow]Id não encontrado.[/]")


@mem_app.command("editar")
def mem_editar(id_lembranca: int, texto: Optional[str] = typer.Option(None, help="novo texto (vira literal do usuário)"),
               escopo: Optional[str] = typer.Option(None, help="global ou projeto:<id>"),
               fixar: Optional[bool] = typer.Option(None, "--fixar/--desafixar", help="fixado nunca é esquecido"),
               confirmar: bool = typer.Option(False, help="marca como literal do usuário (você confirma)")):
    """Edita, move, fixa ou confirma uma lembrança."""
    from .memoria.armazenamento import Memoria

    x = Memoria(_cfg()).atualizar(id_lembranca, texto, escopo, None, "usuario" if confirmar else None, fixar)
    console.print(f"[green]{x.rotulo()} {escape(x.texto)}[/]" if x else "[yellow]Id não encontrado.[/]")


@mem_app.command("esquecer-antigos")
def mem_esquecer_antigos(escopo: Optional[str] = typer.Option(None, help="global ou projeto:<id>"),
                         dias: Optional[float] = typer.Option(None, help="prazo em dias (padrão: config memoria.dias_para_esquecer)")):
    """Esquece fatos inferidos não usados e o excesso por escopo (literais e fixados ficam)."""
    from .memoria.armazenamento import Memoria

    ids = Memoria(_cfg()).esquecer_antigos(escopo, dias)
    console.print(f"[green]{len(ids)} lembrança(s) esquecida(s).[/]")


# ------------------------------------------------------------------ config
def _salvar_cfg(cfg: Config) -> None:
    """Salva a lista de pastas da biblioteca preservando os comentários do config.yaml."""
    import json

    import yaml

    alvo = Path(cfg.caminho_arquivo or "config.yaml")
    if alvo.exists():
        linhas = alvo.read_text(encoding="utf-8").splitlines()
        try:
            ini = linhas.index("biblioteca:")
        except ValueError:
            ini = -1
        if ini >= 0:
            j = ini + 1
            while j < len(linhas) and (linhas[j].startswith(" ") or not linhas[j].strip()):
                if linhas[j].startswith("  pastas:"):
                    k = j + 1
                    while k < len(linhas) and linhas[k].startswith("    -"):
                        k += 1
                    novo_bloco = ["  pastas:"] + [f"    - {json.dumps(p, ensure_ascii=False)}" for p in cfg.biblioteca.pastas] \
                        if cfg.biblioteca.pastas else ["  pastas: []"]
                    texto = "\n".join(linhas[:j] + novo_bloco + linhas[k:]) + "\n"
                    if (yaml.safe_load(texto) or {}).get("biblioteca", {}).get("pastas") == cfg.biblioteca.pastas:
                        alvo.write_text(texto, encoding="utf-8")
                        return
                    break
                j += 1
    cfg.salvar(alvo)


@cfg_app.command("criar")
def cfg_criar(backend: str = typer.Option("ollama", help="ollama | lmstudio | llamacpp | openai_compat"),
              destino: Path = typer.Option(Path("config.yaml"), help="onde salvar"),
              modelo: str = typer.Option("", help="modelo de chat (padrão do backend se vazio)"),
              sobrescrever: bool = typer.Option(False, "--sobrescrever"),
              idioma_cfg: str = typer.Option("pt", "--idioma-padrao", help="pt | en")):
    """Cria um config.yaml comentado (modelo "auto": o NLR detecta o modelo carregado e o contexto real)."""
    from .config_modelo import gerar

    if destino.exists() and not sobrescrever:
        _erro(AgenteErro(f"{destino} já existe (use --sobrescrever)."))
    if backend not in ("ollama", "lmstudio", "llamacpp", "openai_compat"):
        _erro(AgenteErro(f"backend '{backend}' desconhecido; use ollama, lmstudio, llamacpp ou openai_compat."))
    destino.write_text(gerar(backend, modelo, idioma_cfg), encoding="utf-8")
    env = destino.parent / ".env"
    if not env.exists():
        env.write_text("# Segredos (chaves de API). Este arquivo NÃO deve ser compartilhado.\n"
                       "# OPENROUTER_API_KEY=coloque_sua_chave_aqui\n# OPENAI_API_KEY=\n", encoding="utf-8")
    console.print(f"[green]Criado {destino.resolve()} (backend: {backend}).[/] Edite se quiser e rode: nlr doctor")


@cfg_app.command("mostrar")
def cfg_mostrar():
    """Mostra a configuração efetiva."""
    cfg = _cfg()
    console.print(f"[dim]Arquivo: {cfg.caminho_arquivo or '(nenhum — padrões)'}[/]")
    console.print(cfg.para_yaml(), highlight=False, markup=False)


@cfg_app.command("caminho")
def cfg_caminho():
    """Mostra onde está o config.yaml em uso."""
    cfg = _cfg()
    console.print(cfg.caminho_arquivo or "(nenhum config.yaml; usando padrões)")


# ------------------------------------------------------------------ diagnóstico / ferramentas / ui
@app.command()
def doctor(sem_web: bool = typer.Option(False, "--sem-web"), sem_mcp: bool = typer.Option(False, "--sem-mcp")):
    """Verifica instalação, servidor de modelos, embeddings, biblioteca, internet e MCP."""
    from .doctor import diagnosticar

    cfg = _cfg()
    itens = diagnosticar(cfg, testar_web=not sem_web, testar_mcp=not sem_mcp)
    t = Table(title="Diagnóstico do Neuron Local Research")
    t.add_column("")
    t.add_column("item")
    t.add_column("detalhe")
    icone = {"ok": "[green]OK[/]", "aviso": "[yellow]AVISO[/]", "erro": "[red]ERRO[/]"}
    for st, nome, det in itens:
        t.add_row(icone[st], nome, escape(str(det)))
    console.print(t)
    if any(st == "erro" for st, _, _ in itens):
        from .i18n import t as tr
        console.print(f"[red]{tr('cli.erros')}[/]")
        raise typer.Exit(1)


@app.command()
def ferramentas(mcp: bool = typer.Option(False, "--mcp", help="conecta os servidores MCP para listar as deles")):
    """Lista as ferramentas disponíveis (internas, plugins e MCP)."""
    cfg = _cfg()
    serv = _servicos(cfg, mcp=mcp)
    try:
        t = Table(title="Ferramentas")
        t.add_column("nome", no_wrap=True, style="bold")
        for c in ("permissão", "grupos", "origem"):
            t.add_column(c)
        t.add_column("descrição", ratio=1)
        for f in serv.registro.listar():
            t.add_row(f.nome, f.permissao, ",".join(sorted(f.grupos)), f.origem.replace("nlr.ferramentas.", ""),
                      f.descricao[:70])
        console.print(t)
        if serv.plugins:
            console.print(f"Plugins carregados: {', '.join(serv.plugins)}")
    finally:
        serv.fechar()


@app.command()
def ui(porta: Optional[int] = typer.Option(None), host: Optional[str] = typer.Option(None),
       abrir: bool = typer.Option(True, help="abre o navegador"),
       gradio: bool = typer.Option(False, "--gradio", help="usa a interface antiga (Gradio, opcional)")):
    """Abre a interface web estilo ChatGPT em http://127.0.0.1:7860"""
    cfg = _cfg()
    if gradio:
        from .ui.web import iniciar as iniciar_gradio

        iniciar_gradio(cfg, host=host or cfg.ui.host, porta=porta or cfg.ui.porta, abrir=abrir)
        return
    from .api.app import iniciar
    from .i18n import t as tr

    h, p = host or cfg.ui.host, porta or cfg.ui.porta
    console.print(tr("cli.api_iniciando", host=h, porta=p))
    iniciar(cfg, host=h, porta=p, abrir=abrir)


@app.command()
def modelos():
    """Mostra os modelos do servidor, qual está carregado, o contexto real e o perfil escolhido."""
    from .llm.cliente import ClienteLLM
    from .nucleo import hardware

    cfg = _cfg()
    llm = ClienteLLM(cfg, eventos=lambda m: console.print(f"[yellow]• {escape(m)}[/]"))
    console.print(hardware.resumo())
    try:
        info = llm.preparar()
    except AgenteErro as e:
        _erro(e)
    t_ = Table(title=f"{cfg.modelo.backend} — {info['base_url']}")
    for c in ("modelo", "tipo", "carregado", "contexto", "params (B)"):
        t_.add_column(c)
    for m in info["modelos"]:
        marca = " ←" if m["id"] in (info["modelo_chat"], info["modelo_embeddings"]) else ""
        t_.add_row(m["id"] + marca, m["tipo"], "sim" if m["carregado"] else "", str(m["contexto_carregado"] or m["contexto_max"] or ""),
                   str(round(m["parametros_b"], 2) or ""))
    console.print(t_)
    p = info["perfil"]
    from .i18n import t as tr

    console.print(tr("perfil.escolhido", perfil=tr(f"perfil.{p['nome']}"), ferr=p["max_ferramentas"], passos=p["max_passos"],
                     ctx=info["contexto_tokens"]))


@app.command()
def benchmark(rapido: bool = typer.Option(False, "--rapido", help="só velocidade e JSON"),
              historico: bool = typer.Option(False, "--historico", help="mostra os resultados salvos")):
    """Mede o modelo carregado (tokens/s, JSON, ferramentas, inhearsay) e recomenda perfil e contexto."""
    from . import benchmark as bm

    cfg = _cfg()
    if historico:
        t_ = Table(title="Benchmarks")
        for c in ("quando", "modelo", "tok/s", "JSON 1ª", "JSON", "ferramentas", "inhearsay", "perfil rec."):
            t_.add_column(c)
        for r in bm.historico(cfg):
            t_.add_row(r["quando"], r["modelo"], str(r["tokens_por_segundo"]), f"{r['json_primeira']:.0%}",
                       f"{r['json_com_correcao']:.0%}", f"{r['ferramentas']:.0%}", f"{r['inhearsay']:.0%}",
                       r["recomendacao"].get("perfil", ""))
        console.print(t_)
        return
    serv = _servicos(cfg)
    try:
        r = bm.executar(serv, progresso=lambda s: console.print(f"[cyan]• {s}[/]"), rapido=rapido)
        caminho = bm.salvar(cfg, r)
    except AgenteErro as e:
        _erro(e)
    finally:
        serv.fechar()
    t_ = Table(title=f"Benchmark — {r.modelo} ({r.backend}, contexto {r.contexto})")
    t_.add_column("medida")
    t_.add_column("resultado")
    t_.add_row("velocidade", f"{r.tokens_por_segundo} tokens/s ({r.segundos_resposta}s)")
    t_.add_row("JSON na 1ª tentativa / com correção", f"{r.json_primeira:.0%} / {r.json_com_correcao:.0%}")
    if not rapido:
        t_.add_row("tarefas com ferramentas", f"{r.ferramentas:.0%}")
        t_.add_row("taxa de inhearsay (menor é melhor)", f"{r.inhearsay:.0%}")
    rec = r.recomendacao
    t_.add_row("[bold]recomendado[/]", f"perfil {rec['perfil']}, contexto {rec['contexto_tokens']}; bom para: "
               f"{', '.join(rec['bom_para'])}. {rec['dica']}")
    console.print(t_)
    console.print(f"[green]Salvo em {caminho}[/]")


@app.command()
def hardware():
    """Mostra RAM/GPU/VRAM detectadas e o tamanho de modelo recomendado."""
    from .i18n import t as tr
    from .nucleo import hardware as hw_mod

    _cfg()
    hw = hw_mod.detectar()
    console.print(hw_mod.resumo(hw))
    console.print(tr("hw.recomendacao", b=hw.max_parametros_b()))


@app.command()
def api(porta: int = typer.Option(8765), host: str = typer.Option("127.0.0.1"),
        abrir: bool = typer.Option(False, help="abre a interface no navegador")):
    """Inicia a API HTTP (base da nova interface estilo ChatGPT). Documentação em /docs."""
    from .api.app import iniciar
    from .i18n import t as tr

    cfg = _cfg()
    console.print(tr("cli.api_iniciando", host=host, porta=porta))
    iniciar(cfg, host=host, porta=porta, abrir=abrir)


def _idioma_argv() -> str:
    """Idioma para o --help: --idioma/--lang na linha de comando > NLR_IDIOMA > config.yaml > pt."""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a in ("--idioma", "--lang", "-l") and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(("--idioma=", "--lang=")):
            return a.split("=", 1)[1]
    if os.environ.get("NLR_IDIOMA"):
        return os.environ["NLR_IDIOMA"]
    try:
        return carregar(None).idioma or "pt"
    except Exception:  # noqa: BLE001
        return "pt"


def comando_traduzido(idioma: str):
    """Comando click do app com os textos de ajuda no idioma pedido (en usa nlr/i18n/ajuda_cli.py)."""
    import typer.main

    cmd = typer.main.get_command(app)
    if not str(idioma).lower().startswith("en"):
        return cmd
    from .i18n.ajuda_cli import EN

    def tr(x):
        return EN.get(x, x) if x else x

    def walk(c):
        c.help, c.short_help = tr(c.help), tr(c.short_help)
        for p in c.params:
            if getattr(p, "help", None):
                p.help = tr(p.help)
        for sub in getattr(c, "commands", {}).values():
            walk(sub)
    walk(cmd)
    return cmd


def main():
    try:
        comando_traduzido(_idioma_argv())(prog_name="nlr")
    except AgenteErro as e:
        console.print(f"[bold red]{escape(str(e))}[/]")
        sys.exit(1)


if __name__ == "__main__":
    main()
