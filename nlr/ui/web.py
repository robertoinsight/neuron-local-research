"""Interface web (Gradio): conversa, pesquisa, projetos, biblioteca, memória e diagnóstico.

Por segurança, a interface web NÃO tem como confirmar comandos um a um: comandos só rodam se você marcar
"modo autônomo" na aba Projetos (e apenas os da lista seguranca.comandos_permitidos). O resto é negado.
A interface escuta só em 127.0.0.1 (seu computador), a menos que você mude ui.host.
"""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Iterator, List

import gradio as gr

from ..config import Config
from ..erros import AgenteErro
from ..i18n import idioma_atual
from ..i18n.gradio_en import EN as _GRADIO_EN


def _g(texto: str) -> str:
    """Texto da interface Gradio no idioma atual (pt padrão; en via nlr/i18n/gradio_en.py)."""
    return _GRADIO_EN.get(texto, texto) if idioma_atual() == "en" else texto


class _Fila:
    """Junta eventos de uma thread de trabalho para o gerador do Gradio exibir."""

    def __init__(self):
        self.q: "queue.Queue" = queue.Queue()

    def evento(self, tipo: str, msg: str) -> None:
        if tipo in ("pensamento", "observacao"):
            return
        self.q.put(("evento", f"[{time.strftime('%H:%M:%S')}] {tipo}: {msg[:400]}"))

    def texto(self, t: str) -> None:
        self.q.put(("texto", t))


def _em_thread(alvo, fila: _Fila):
    res = {}

    def run():
        try:
            res["ok"] = alvo()
        except BaseException as e:  # noqa: BLE001
            res["erro"] = e
        finally:
            fila.q.put(("fim", None))

    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th, res


def construir(cfg: Config):
    from ..agentes.chat import SessaoChat
    from ..agentes.pesquisa import pesquisar
    from ..agentes.projeto import ExecutorProjeto
    from ..agentes.projeto_store import STATUS_ICONE, ProjetoStore
    from ..biblioteca.busca import buscar
    from ..doctor import diagnosticar
    from ..servicos import Servicos

    serv = Servicos(cfg, confirmar=None, usar_mcp=bool(cfg.mcp.servidores))
    store = ProjetoStore(cfg)
    sessoes: dict = {}

    # ---------------------------------------------------------------- conversa
    def conversar(msg: str, historico: List[dict], modo: str, sid: str) -> Iterator:
        if not msg.strip():
            yield historico, "", sid
            return
        fila = _Fila()
        sessao = sessoes.get(sid) if sid else None
        if sessao is None:
            sessao = SessaoChat(serv, sid or None, eventos=fila.evento)
            sessoes[sessao.id] = sessao
        sessao.ctx.eventos = fila.evento
        sid = sessao.id
        historico = list(historico or []) + [{"role": "user", "content": msg},
                                             {"role": "assistant", "content": "…"}]
        yield historico, "", sid
        partes: List[str] = []
        status: List[str] = []
        th, res = _em_thread(lambda: sessao.responder(msg, modo, ao_receber=fila.texto), fila)
        while True:
            tipo, valor = fila.q.get()
            if tipo == "fim":
                break
            if tipo == "texto":
                partes.append(valor)
            else:
                status.append(valor)
            corpo = "".join(partes) or ("_" + (status[-1] if status else "pensando...") + "_")
            historico[-1] = {"role": "assistant", "content": corpo}
            yield historico, "", sid
        th.join()
        if "erro" in res:
            historico[-1] = {"role": "assistant", "content": f"**Erro:** {res['erro']}"}
        else:
            r = res["ok"]
            texto = r.texto + ("".join(f"\n\n> Aviso: {a}" for a in r.avisos))
            historico[-1] = {"role": "assistant", "content": texto}
        yield historico, "", sid

    # ---------------------------------------------------------------- pesquisa
    def pesquisar_ui(pergunta: str, fontes: str) -> Iterator[str]:
        if not pergunta.strip():
            yield "Digite uma pergunta."
            return
        fila = _Fila()
        ctx = serv.contexto(cfg.dir_dados / "area_de_trabalho", eventos=fila.evento)
        th, res = _em_thread(lambda: pesquisar(ctx, pergunta, usar_biblioteca=fontes in ("biblioteca", "ambos"),
                                               usar_web=fontes in ("web", "ambos"), ao_receber=fila.texto), fila)
        partes, status = [], []
        while True:
            tipo, valor = fila.q.get()
            if tipo == "fim":
                break
            (partes if tipo == "texto" else status).append(valor)
            yield "".join(partes) or "_" + (status[-1] if status else "...") + "_"
        th.join()
        if "erro" in res:
            yield f"**Erro:** {res['erro']}"
        else:
            r = res["ok"]
            yield r.texto_completo() + "".join(f"\n\n> Aviso: {a}" for a in r.avisos)

    # ---------------------------------------------------------------- projetos
    def lista_projetos():
        return gr.update(choices=[f"{p.id}" for p in store.listar()])

    def status_md(pid: str) -> str:
        if not pid:
            return _g("Selecione um projeto.")
        try:
            info = store.carregar(pid)
        except AgenteErro as e:
            return str(e)
        resumo, tarefas = store.carregar_tarefas(info)
        linhas = [f"### {info.nome}", f"**status:** {info.status} · **fase:** {info.fase}", f"**pasta:** `{info.pasta}`"]
        if info.erro:
            linhas.append(f"**erro:** {info.erro}")
        if resumo:
            linhas.append(f"\n{resumo}\n")
        linhas += [f"- `{STATUS_ICONE.get(t['status'], '?')}` **{t['id']}. {t['titulo']}** ({t['tipo']})" for t in tarefas]
        rel = Path(info.pasta) / "RELATORIO.md"
        if rel.exists():
            linhas.append("\n---\n" + rel.read_text(encoding="utf-8")[:6000])
        return _g("\n").join(linhas)

    def rodar_projeto(acao: str, objetivo: str, nome: str, pid: str, autonomo: bool) -> Iterator:
        fila = _Fila()
        antigo = cfg.seguranca.modo_autonomo
        cfg.seguranca.modo_autonomo = bool(autonomo)
        ex = ExecutorProjeto(serv, eventos=fila.evento, confirmar=None)
        if acao == "novo":
            if not objetivo.strip():
                yield _g("Descreva o objetivo do projeto."), gr.update(), ""
                return
            alvo = lambda: ex.novo(objetivo, nome or None)  # noqa: E731
        else:
            if not pid:
                yield _g("Selecione um projeto para retomar."), gr.update(), ""
                return
            alvo = lambda: ex.retomar(pid)  # noqa: E731
        log: List[str] = []
        th, res = _em_thread(alvo, fila)
        while True:
            tipo, valor = fila.q.get()
            if tipo == "fim":
                break
            log.append(valor)
            yield "\n".join(log[-200:]), gr.update(), ""
        th.join()
        cfg.seguranca.modo_autonomo = antigo
        ex.fechar()
        if "erro" in res:
            log.append(f"ERRO: {res['erro']}")
            yield "\n".join(log[-200:]), lista_projetos(), ""
        else:
            info = res["ok"]
            yield "\n".join(log[-200:]), gr.update(choices=[p.id for p in store.listar()], value=info.id), status_md(info.id)

    # ---------------------------------------------------------------- biblioteca
    def bib_info() -> str:
        st = serv.indice.status()
        return (f"**Pastas:** {', '.join(cfg.biblioteca.pastas) or '(nenhuma)'}  \n"
                f"**Arquivos:** {st['arquivos']} · **trechos:** {st['trechos']} · **com vetor:** {st['trechos_com_vetor']} · "
                f"**embeddings:** {st['embedder']}")

    def bib_adicionar(pasta: str) -> str:
        p = Path(pasta.strip().strip('"')).expanduser()
        if not p.exists():
            return f"A pasta não existe: {p}\n\n" + bib_info()
        if str(p.resolve()) not in cfg.biblioteca.pastas:
            cfg.biblioteca.pastas.append(str(p.resolve()))
            from ..cli import _salvar_cfg

            _salvar_cfg(cfg)
        return _g("Pasta adicionada. Clique em Indexar.\n\n") + bib_info()

    def bib_indexar(forcar: bool) -> Iterator[str]:
        fila = _Fila()
        th, res = _em_thread(lambda: serv.indice.indexar(forcar=forcar, progresso=lambda s: fila.evento("status", s)), fila)
        log = []
        while True:
            tipo, valor = fila.q.get()
            if tipo == "fim":
                break
            log.append(valor)
            yield "\n".join(log[-30:])
        th.join()
        if "erro" in res:
            yield "\n".join(log[-30:]) + f"\n\nERRO: {res['erro']}"
        else:
            r = res["ok"]
            extra = "".join(f"\n- erro em {a}: {e}" for a, e in r.erros[:10])
            yield r.resumo() + extra + ("\n\nAviso: " + r.aviso_embeddings if r.aviso_embeddings else "") + "\n\n" + bib_info()

    def bib_buscar(consulta: str) -> str:
        if not consulta.strip():
            return ""
        res = buscar(serv.indice, consulta)
        return _g("\n\n").join(f"**[{i}] {r.rotulo}**\n\n{r.texto[:800]}" for i, r in enumerate(res, 1)) or _g("Nada encontrado.")

    # ---------------------------------------------------------------- memória
    def mem_tabela():
        return [[m.id, m.escopo, m.tipo, m.rotulo(), m.texto] for m in serv.memoria.listar(None, 300)]

    def mem_add(texto: str, tipo: str):
        if texto.strip():
            serv.memoria.lembrar(texto, tipo, "global", origem="usuario")
        return mem_tabela(), ""

    def mem_del(lid):
        try:
            serv.memoria.esquecer(int(lid))
        except (TypeError, ValueError):
            pass
        return mem_tabela()

    def doctor_md() -> str:
        icone = {"ok": "✅", "aviso": "⚠️", "erro": "❌"}
        itens = diagnosticar(cfg, testar_web=True, testar_mcp=False)
        return _g("| | item | detalhe |\n|---|---|---|\n") + "\n".join(
            f"| {icone[s]} | {n} | {d.replace('|', '/').replace(chr(10), ' ')} |" for s, n, d in itens)

    # ---------------------------------------------------------------- imagem (v0.7)
    def imagem_ui(arquivo, acao: str, pergunta: str) -> str:
        from pathlib import Path

        from ..ferramentas import visao

        if not arquivo:
            return _g("Envie uma imagem primeiro.")
        p = Path(arquivo)
        try:
            if acao == "pesquisar":
                ctx = serv.contexto(cfg.dir_dados / "area_de_trabalho")
                r = visao.pesquisar(serv.llm, cfg, ctx.web, p, pergunta)
                refs = "\n".join(f"- [{f.n}] [{f.titulo}]({f.referencia})" for f in r.fontes)
                corpo = r.texto + (f"\n\n**{_g('Fontes')}**\n{refs}" if refs else "")
            else:
                r = visao.analisar(serv.llm, cfg, [p], acao, pergunta)
                corpo = r.texto
        except AgenteErro as e:
            return f"**{_g('Erro')}:** {e}"
        avisos = "".join(f"\n\n> ⚠ {a}" for a in r.avisos)
        return f"_{r.info} · {r.modo} · {r.modelo}_\n\n{corpo}{avisos}"

    # ---------------------------------------------------------------- layout
    with gr.Blocks(title="Neuron Local Research") as demo:
        gr.Markdown(f"# 🤖 Neuron Local Research\n{_g('Modelo')}: **{cfg.modelo.modelo_chat}** ({cfg.modelo.backend}) · "
                    f"config: `{cfg.caminho_arquivo or 'padrões'}`")
        with gr.Tab(_g("Conversa")):
            sid = gr.State("")
            chatbot = gr.Chatbot(height=520, label=_g("Conversa"))
            with gr.Row():
                entrada = gr.Textbox(placeholder=_g("Escreva sua mensagem e tecle Enter"), scale=8, show_label=False)
                modo = gr.Dropdown(["auto", "conversa", "biblioteca", "web", "ambos", "agente"], value="auto",
                                   label=_g("modo"), scale=2)
            with gr.Row():
                enviar = gr.Button(_g("Enviar"), variant="primary")
                nova = gr.Button(_g("Nova conversa"))
            entrada.submit(conversar, [entrada, chatbot, modo, sid], [chatbot, entrada, sid])
            enviar.click(conversar, [entrada, chatbot, modo, sid], [chatbot, entrada, sid])
            nova.click(lambda: ([], "", ""), None, [chatbot, entrada, sid])
        with gr.Tab(_g("Imagem")):
            with gr.Row():
                with gr.Column(scale=2):
                    img = gr.Image(type="filepath", label=_g("Imagem"), sources=["upload", "clipboard"])
                    acao_img = gr.Radio(["minucioso", "geral", "texto", "pixel", "pesquisar"], value="minucioso",
                                        label=_g("Ação"))
                    perg_img = gr.Textbox(label=_g("Pergunta ou foco (opcional)"))
                    bt_img = gr.Button(_g("Analisar"), variant="primary")
                with gr.Column(scale=3):
                    saida_img = gr.Markdown()
            bt_img.click(imagem_ui, [img, acao_img, perg_img], saida_img)
        with gr.Tab(_g("Pesquisa profunda")):
            pergunta = gr.Textbox(label=_g("Pergunta"), placeholder=_g("Ex.: O que meus documentos e a internet dizem sobre ...?"))
            fontes = gr.Radio(["ambos", "biblioteca", "web"], value="ambos", label=_g("Fontes"))
            bt_pesq = gr.Button(_g("Pesquisar"), variant="primary")
            saida_pesq = gr.Markdown()
            bt_pesq.click(pesquisar_ui, [pergunta, fontes], saida_pesq)
        with gr.Tab(_g("Projetos")):
            with gr.Row():
                with gr.Column(scale=3):
                    objetivo = gr.Textbox(label=_g("Objetivo do projeto"), lines=4,
                                          placeholder=_g("Ex.: Pesquise na minha biblioteca e na internet e desenvolva ..."))
                    nome = gr.Textbox(label=_g("Nome curto (opcional)"))
                    autonomo = gr.Checkbox(label=_g("Modo autônomo nesta execução (permite rodar os comandos da lista de permitidos sem perguntar; os demais são negados)"), value=False)
                    bt_novo = gr.Button(_g("Criar e executar projeto"), variant="primary")
                with gr.Column(scale=2):
                    sel = gr.Dropdown(choices=[p.id for p in store.listar()], label=_g("Projetos"), interactive=True)
                    with gr.Row():
                        bt_ret = gr.Button(_g("Retomar"))
                        bt_atual = gr.Button(_g("Atualizar lista"))
            log_proj = gr.Textbox(label=_g("Andamento"), lines=14, max_lines=30, autoscroll=True)
            status_proj = gr.Markdown()
            vazio = gr.State("")
            bt_novo.click(lambda o, n, a: rodar_projeto("novo", o, n, "", a), [objetivo, nome, autonomo],
                          [log_proj, sel, status_proj])
            bt_ret.click(lambda p, a: rodar_projeto("retomar", "", "", p, a), [sel, autonomo], [log_proj, sel, status_proj])
            bt_atual.click(lista_projetos, None, sel)
            sel.change(status_md, sel, status_proj)
            _ = vazio
        with gr.Tab(_g("Biblioteca")):
            info_bib = gr.Markdown(bib_info())
            with gr.Row():
                pasta = gr.Textbox(label=_g("Adicionar pasta"), placeholder=r"C:\Users\voce\Documents\Biblioteca", scale=4)
                bt_add = gr.Button(_g("Adicionar"), scale=1)
            with gr.Row():
                forcar = gr.Checkbox(label=_g("Reprocessar tudo"), value=False)
                bt_idx = gr.Button(_g("Indexar (incremental)"), variant="primary")
            log_idx = gr.Textbox(label=_g("Indexação"), lines=8)
            consulta = gr.Textbox(label=_g("Buscar trechos (sem usar o modelo)"))
            res_busca = gr.Markdown()
            bt_add.click(bib_adicionar, pasta, info_bib)
            bt_idx.click(bib_indexar, forcar, log_idx)
            consulta.submit(bib_buscar, consulta, res_busca)
        with gr.Tab(_g("Memória")):
            tabela = gr.Dataframe(value=mem_tabela(), headers=["id", _g("escopo"), _g("tipo"), _g("origem"), _g("texto")], interactive=False, wrap=True)
            with gr.Row():
                nova_mem = gr.Textbox(label=_g("Nova lembrança"), scale=4)
                tipo_mem = gr.Dropdown(["fato", "preferencia", "decisao", "licao"], value="fato", label=_g("tipo"), scale=1)
                bt_mem = gr.Button(_g("Guardar"), scale=1)
            with gr.Row():
                id_del = gr.Number(label=_g("id para apagar"), precision=0)
                bt_del = gr.Button(_g("Apagar"))
            bt_mem.click(mem_add, [nova_mem, tipo_mem], [tabela, nova_mem])
            bt_del.click(mem_del, id_del, tabela)
        with gr.Tab(_g("Sistema")):
            bt_doc = gr.Button(_g("Rodar diagnóstico (doctor)"))
            out_doc = gr.Markdown()
            bt_doc.click(doctor_md, None, out_doc)
            gr.Markdown(_g("Comandos pela interface web só rodam no **modo autônomo** e se estiverem em `seguranca.comandos_permitidos`. Para aprovar comandos um a um, use a linha de comando (`nlr projeto novo ...`)."))
    demo.queue(default_concurrency_limit=2)
    demo._agente_servicos = serv  # para testes
    return demo


def iniciar(cfg: Config, host: str = "127.0.0.1", porta: int = 7860, abrir: bool = True):
    demo = construir(cfg)
    print(f"Interface web em http://{host}:{porta}  (Ctrl+C para sair)")
    demo.launch(server_name=host, server_port=porta, inbrowser=abrir, show_error=True)
