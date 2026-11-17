"""API HTTP + interface web do Neuron Local Research (FastAPI).

A interface estilo ChatGPT (nlr/api/static) é servida em "/" e funciona offline (sem CDN).
Rotas principais (JSON; chat com streaming SSE; tarefas longas como "jobs" consultados por polling):
  GET  /api/saude · GET /api/modelos · PUT /api/modelo · GET/PUT /api/configuracoes · PUT /api/idioma
  GET  /api/i18n/{idioma}
  GET  /api/chats?q= · POST /api/chats · GET/PATCH/DELETE /api/chats/{id} · POST /api/chats/{id}/mensagens
  POST /api/upload            {"nome", "dados_b64", "destino": "chat"|"biblioteca"}  (imagem no chat -> /api/imagens)
  POST /api/imagens           {"nome", "dados_b64"} -> {"id", "largura", "altura", "miniatura", "url"} · GET /api/imagens/{id}
  GET  /api/visao             estado do modelo de visão (tem visão? carregado? avisos) e da busca reversa
  POST /api/imagem/analisar   {"imagem" | "imagens", "modo", "pergunta", "job"} · POST /api/imagem/pesquisar {"imagem", "foco"}
  POST /api/chats/{id}/mensagens também aceita {"imagens": [ids], "acao_imagem": "minucioso|texto|pixel|pesquisar|geral"}
  POST /api/pesquisa          {"pergunta", "profundidade", "largura", "fontes"}  -> job
  GET  /api/relatorios · GET /api/relatorios/{nome}
  GET  /api/projetos · GET /api/projetos/{id} · POST /api/projetos {"objetivo", "nome", "autonomo"} -> job
  GET  /api/jobs/{id}?desde=0
  POST /api/benchmark -> job · GET /api/benchmarks
Só para 127.0.0.1 (sem autenticação). Não exponha na rede sem um proxy com senha.
"""
from __future__ import annotations

import base64
import json
import queue
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel

from .. import __version__
from .. import imagens as imagens_mod
from ..config import Config
from ..erros import AgenteErro
from ..i18n import definir_idioma, idioma_atual, iniciar as iniciar_i18n

ESTATICOS = Path(__file__).resolve().parent / "static"
MODOS_UI = ["auto", "conversa", "biblioteca", "web", "ambos", "agente", "profunda", "projeto"]


class NovaMensagem(BaseModel):
    texto: str
    modo: str = "auto"
    stream: bool = False
    anexos: List[str] = []  # textos de arquivos enviados com /api/upload destino=chat
    imagens: List[str] = []  # ids de /api/imagens (v0.7)
    acao_imagem: str = ""  # minucioso | geral | texto | pixel | pesquisar | "" (automático)


class NovaImagem(BaseModel):
    nome: str = "imagem.png"
    dados_b64: str


class PedidoImagem(BaseModel):
    imagem: str = ""  # id de /api/imagens
    imagens: List[str] = []
    modo: str = ""  # minucioso | geral | texto | pixel
    pergunta: str = ""
    foco: str = ""
    job: bool = False  # true = roda em segundo plano (consulte /api/jobs/{id})


class Idioma(BaseModel):
    idioma: str


class NovoChat(BaseModel):
    titulo: str = ""


class NovaLembranca(BaseModel):
    texto: str
    escopo: str = "global"
    tipo: str = "fato"

class EditaLembranca(BaseModel):
    texto: Optional[str] = None
    escopo: Optional[str] = None
    tipo: Optional[str] = None
    marca: Optional[str] = None
    fixada: Optional[bool] = None


class PedidoKits(BaseModel):
    pixel: Optional[bool] = None
    abnt: Optional[bool] = None
    aseprite: Optional[str] = None
    salvar: bool = True


class PedidoPixel(BaseModel):
    acao: str  # redimensionar | upscale | remover_fundo | aplicar_paleta | reduzir_paleta | extrair_paleta | preview | montar | fatiar | gif | aseprite_sheet
    imagens_b64: List[str] = []  # PNG/GIF/JPG/.aseprite em base64 (montar/gif: vários)
    nome: str = "imagem.png"
    largura: int = 0
    altura: int = 0
    fator: float = 0
    paleta: str = ""
    cores: int = 16
    dither: bool = False
    cor_fundo: str = ""
    tolerancia: int = 0
    colunas: int = 0
    duracao_ms: int = 100


class PedidoAbntRef(BaseModel):
    identificadores: List[str]


class PedidoAbntDoc(BaseModel):
    titulo: str
    autor: str = ""
    subtitulo: str = ""
    instituicao: str = ""
    curso: str = ""
    local: str = ""
    ano: str = ""
    natureza: str = ""
    orientador: str = ""
    texto: str = ""  # markdown
    referencias: List[str] = []  # DOI/ISBN/URL
    referencias_prontas: List[dict] = []  # Referencia.dict()


class Renomear(BaseModel):
    titulo: Optional[str] = None
    projeto: Optional[str] = None


class Modelo(BaseModel):
    modelo_chat: str


class Configuracoes(BaseModel):
    idioma: Optional[str] = None
    backend: Optional[str] = None
    base_url: Optional[str] = None
    modelo_chat: Optional[str] = None
    salvar: bool = True


class Upload(BaseModel):
    nome: str
    dados_b64: str
    destino: str = "chat"


class PedidoPesquisa(BaseModel):
    pergunta: str
    profundidade: int = 0
    largura: int = 0
    fontes: str = "web"
    chat: str = ""
    abnt: bool = False  # também gera o .docx ABNT (NBR 14724, citações autor-data)


class PedidoProjeto(BaseModel):
    objetivo: str
    nome: Optional[str] = None
    autonomo: bool = False


class Jobs:
    def __init__(self):
        self._d: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def criar(self, tipo: str, titulo: str) -> dict:
        j = {"id": uuid.uuid4().hex[:10], "tipo": tipo, "titulo": titulo, "estado": "rodando", "eventos": [],
             "resultado": None, "erro": "", "inicio": time.time()}
        with self._lock:
            self._d[j["id"]] = j
        return j

    def evento(self, j: dict, dado: dict) -> None:
        with self._lock:
            j["eventos"].append({"t": round(time.time() - j["inicio"], 1), **dado})

    def obter(self, jid: str) -> Optional[dict]:
        return self._d.get(jid)

    def listar(self) -> List[dict]:
        return [{k: v for k, v in j.items() if k != "eventos"} for j in self._d.values()]


def criar_app(cfg: Config, servicos=None):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles

    iniciar_i18n(cfg)
    if servicos is None:
        from ..servicos import Servicos

        servicos = Servicos(cfg)
    serv = servicos
    trava = threading.Lock()  # um modelo local atende uma geração por vez
    jobs = Jobs()
    app = FastAPI(title="Neuron Local Research", version=__version__)
    app.state.serv = serv
    app.state.jobs = jobs

    def rodar_job(j: dict, fn) -> None:
        def alvo():
            with trava:
                try:
                    j["resultado"] = fn()
                    j["estado"] = "concluido"
                except AgenteErro as e:
                    j["erro"], j["estado"] = str(e), "erro"
                except Exception as e:  # noqa: BLE001
                    j["erro"], j["estado"] = f"{type(e).__name__}: {e}", "erro"

        threading.Thread(target=alvo, daemon=True).start()

    # ------------------------------------------------------------ interface
    if ESTATICOS.exists():
        app.mount("/static", StaticFiles(directory=str(ESTATICOS)), name="static")

        @app.get("/", include_in_schema=False)
        def raiz():
            return FileResponse(str(ESTATICOS / "index.html"))
    else:  # pragma: no cover
        @app.get("/", include_in_schema=False)
        def raiz():
            return RedirectResponse("/docs")

    @app.get("/api/i18n/{idioma}")
    def textos_ui(idioma: str):
        from ..i18n.ui import UI

        return UI.get("en" if idioma.startswith("en") else "pt")

    # ------------------------------------------------------------ estado / modelos / configurações
    @app.get("/api/saude")
    def saude():
        try:
            serv.llm.preparar()
            ok, erro = True, ""
        except AgenteErro as e:
            ok, erro = False, str(e)
        return {"nome": "Neuron Local Research", "versao": __version__, "idioma": idioma_atual(),
                "servidor_ok": ok, "erro": erro}

    @app.get("/api/modelos")
    def modelos():
        from ..nucleo import hardware

        try:
            info = serv.llm.preparar()
        except AgenteErro as e:
            raise HTTPException(503, str(e))
        info["hardware"] = hardware.detectar().dict()
        return info

    def _reiniciar_llm():
        ep = serv.llm.principal
        ep._resolvido = False
        ep._cliente = None
        serv.llm._ctx_confirmado = False

    @app.put("/api/modelo")
    def trocar_modelo(d: Modelo):
        serv.llm.principal.modelo_chat = d.modelo_chat
        cfg.modelo.modelo_chat = d.modelo_chat
        _reiniciar_llm()
        try:
            return serv.llm.preparar()
        except AgenteErro as e:
            raise HTTPException(503, str(e))

    @app.get("/api/configuracoes")
    def ler_config():
        return {"idioma": idioma_atual(), "backend": cfg.modelo.backend, "base_url": cfg.modelo.url(),
                "modelo_chat": cfg.modelo.modelo_chat, "modos": MODOS_UI, "handoff": cfg.handoff.model_dump(),
                "pastas_biblioteca": cfg.biblioteca.pastas, "versao": __version__}

    @app.put("/api/configuracoes")
    def salvar_config(d: Configuracoes):
        from ..config import BACKENDS_PADRAO

        if d.idioma:
            cfg.idioma = definir_idioma(d.idioma)
        mudou = False
        if d.backend and d.backend != cfg.modelo.backend:
            if d.backend not in BACKENDS_PADRAO:
                raise HTTPException(400, f"backend inválido: {d.backend}")
            cfg.modelo.backend = d.backend
            serv.llm.principal.backend = d.backend
            mudou = True
        if d.base_url is not None and d.base_url.rstrip("/") != cfg.modelo.url():
            cfg.modelo.base_url = d.base_url.rstrip("/")
            serv.llm.principal.base_url = cfg.modelo.url()
            mudou = True
        if d.modelo_chat:
            cfg.modelo.modelo_chat = serv.llm.principal.modelo_chat = d.modelo_chat
            mudou = True
        if mudou:
            _reiniciar_llm()
        if d.salvar and cfg.caminho_arquivo:
            cfg.salvar()
        return ler_config()

    @app.put("/api/idioma")
    def mudar_idioma(d: Idioma):
        cfg.idioma = definir_idioma(d.idioma)
        return {"idioma": cfg.idioma}

    # ------------------------------------------------------------ chats
    def _item_chat(i, tit, at, n_):
        return {"id": i, "titulo": tit, "atualizada": at, "mensagens": n_, "pai": serv.memoria.pai_sessao(i),
                "continuacao": serv.memoria.filho_sessao(i)}

    @app.get("/api/chats")
    def chats(n: int = 100, q: str = ""):
        todos = serv.memoria.listar_sessoes(1000 if q else n)
        if q:
            ids = set(serv.memoria.buscar_sessoes(q, n))
            todos = [x for x in todos if x[0] in ids]
        return [_item_chat(*x) for x in todos[:n]]

    @app.post("/api/chats")
    def novo_chat(d: NovoChat):
        return {"id": serv.memoria.nova_sessao(d.titulo)}

    def _existe(sid: str):
        if not serv.memoria.sessao_existe(sid):
            raise HTTPException(404, "chat não encontrado")

    @app.get("/api/chats/{sid}")
    def ler_chat(sid: str):
        _existe(sid)
        return {"id": sid, "titulo": serv.memoria.titulo_sessao(sid), "cadeia": serv.memoria.cadeia_sessoes(sid),
                "continuacao": serv.memoria.filho_sessao(sid), "projeto": serv.memoria.projeto_sessao(sid), "mensagens": serv.memoria.historico(sid, 10_000)}

    @app.patch("/api/chats/{sid}")
    def renomear_chat(sid: str, d: Renomear):
        _existe(sid)
        if d.titulo is not None:
            serv.memoria.renomear_sessao(sid, d.titulo)
        if d.projeto is not None:
            serv.memoria.definir_projeto_sessao(sid, d.projeto)
        return {"id": sid, "titulo": serv.memoria.titulo_sessao(sid), "projeto": serv.memoria.projeto_sessao(sid)}

    @app.delete("/api/chats/{sid}")
    def apagar_chat(sid: str):
        _existe(sid)
        serv.memoria.apagar_sessao(sid)
        return {"ok": True}

    @app.post("/api/chats/{sid}/mensagens")
    def enviar(sid: str, d: NovaMensagem):
        from ..agentes.chat import SessaoChat

        _existe(sid)
        texto = d.texto
        if d.anexos:
            texto += "\n\n" + "\n\n".join(d.anexos)
        modo = d.modo if d.modo in MODOS_UI else "auto"
        imgs = _caminhos_imagens(d.imagens)

        def responder(s, ao_receber=None):
            if imgs:
                return s.responder_imagem(texto, imgs, d.acao_imagem, marcadores=[p.name for p in imgs],
                                          ao_receber=ao_receber)
            return s.responder(texto, "auto" if modo in ("profunda", "projeto") else modo, ao_receber=ao_receber)

        def fim(r):
            return {"texto": r.texto, "rota": r.rota, "sessao": r.sessao, "avisos": r.avisos,
                    "fontes": [{"n": f.n, "tipo": f.tipo, "titulo": f.titulo, "referencia": f.referencia,
                                "local": f.local, "trecho": f.texto[:400]} for f in r.fontes]}

        if not d.stream:
            with trava:
                s = SessaoChat(serv, sid)
                try:
                    return fim(responder(s))
                except AgenteErro as e:
                    raise HTTPException(502, str(e))

        fila: "queue.Queue[Optional[tuple]]" = queue.Queue()

        def trabalhar():
            with trava:
                try:
                    s = SessaoChat(serv, sid, eventos=lambda tipo, msg: fila.put(
                        ("handoff" if tipo == "handoff" else "evento", {"tipo": tipo, "msg": msg})),
                        confirmar=lambda a, b: False)
                    r = responder(s, ao_receber=lambda p: fila.put(("token", {"t": p})))
                    fila.put(("fim", fim(r)))
                except AgenteErro as e:
                    fila.put(("erro", {"msg": str(e)}))
                except Exception as e:  # noqa: BLE001
                    fila.put(("erro", {"msg": f"{type(e).__name__}: {e}"}))
                finally:
                    fila.put(None)

        threading.Thread(target=trabalhar, daemon=True).start()

        def gerar():
            while True:
                item = fila.get()
                if item is None:
                    break
                ev, dado = item
                yield f"event: {ev}\ndata: {json.dumps(dado, ensure_ascii=False)}\n\n"

        return StreamingResponse(gerar(), media_type="text/event-stream")

    # ------------------------------------------------------------ upload
    @app.post("/api/upload")
    def upload(d: Upload):
        from ..biblioteca.carregadores import carregar_arquivo

        nome = Path(d.nome).name.replace("..", "_")
        try:
            dados = base64.b64decode(d.dados_b64)
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "arquivo inválido (base64)")
        if len(dados) > cfg.biblioteca.max_arquivo_mb * 1024 * 1024:
            raise HTTPException(413, "arquivo grande demais")
        if d.destino == "biblioteca":
            pasta = cfg.dir_dados / "biblioteca_enviados"
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / nome).write_bytes(dados)
            if str(pasta) not in cfg.biblioteca.pastas:
                cfg.biblioteca.pastas.append(str(pasta))
                if cfg.caminho_arquivo:
                    cfg.salvar()
            j = jobs.criar("indexar", nome)
            rodar_job(j, lambda: {"relatorio": str(serv.indice.indexar(
                [pasta], progresso=lambda s: jobs.evento(j, {"etapa": "indexar", "msg": s})))})
            return {"ok": True, "destino": "biblioteca", "arquivo": nome, "job": j["id"]}
        from ..ferramentas.visao import EXTENSOES

        if Path(nome).suffix.lower() in EXTENSOES:  # v0.7: imagem no chat vai para o modelo de visão
            try:
                info = imagens_mod.salvar(cfg, nome, d.dados_b64)
            except AgenteErro as e:
                raise HTTPException(415, str(e))
            return {"ok": True, "destino": "chat", "tipo": "imagem", "arquivo": nome, **info}
        tmp = cfg.dir_dados / "anexos" / f"{uuid.uuid4().hex[:6]}-{nome}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(dados)
        try:
            segs = carregar_arquivo(tmp)
        except AgenteErro as e:
            raise HTTPException(415, str(e))
        texto = "\n".join(s.texto for s in segs)
        lim = int(cfg.modelo.contexto_tokens * 3.5 * 0.4)
        cortado = len(texto) > lim
        return {"ok": True, "destino": "chat", "arquivo": nome, "cortado": cortado,
                "texto": f"[Arquivo: {nome}]\n{texto[:lim]}" + ("\n[...]" if cortado else "")}

    # ------------------------------------------------------------ v0.7: imagens e visão
    def _caminhos_imagens(ids: List[str]) -> List[Path]:
        out = []
        for i in ids[: max(1, cfg.visao.max_imagens)]:
            try:
                out.append(imagens_mod.caminho(cfg, i))
            except AgenteErro as e:
                raise HTTPException(404, str(e))
        return out

    @app.post("/api/imagens")
    def enviar_imagem(d: NovaImagem):
        try:
            return imagens_mod.salvar(cfg, d.nome, d.dados_b64)
        except AgenteErro as e:
            raise HTTPException(415, str(e))

    @app.get("/api/imagens/{iid}")
    def ler_imagem(iid: str):
        try:
            return FileResponse(str(imagens_mod.caminho(cfg, iid)))
        except AgenteErro as e:
            raise HTTPException(404, str(e))

    @app.get("/api/visao")
    def visao_estado():
        from ..ferramentas.visao import estado_visao

        br = cfg.visao.busca_reversa
        import os

        return {**estado_visao(serv.llm, cfg).dict(), "modo_padrao": cfg.visao.modo_padrao,
                "links_manuais": cfg.visao.links_manuais, "max_imagens": cfg.visao.max_imagens,
                "busca_reversa": {"provedor": br.provedor, "consentimento_envio": br.consentimento_envio,
                                  "chave_presente": bool(os.environ.get(br.api_key_env or "SERPAPI_API_KEY")),
                                  "ativa": br.provedor != "desligado" and br.consentimento_envio}}

    def _rodar_imagem(fn, titulo: str, em_job: bool):
        if em_job:
            j = jobs.criar("imagem", titulo)
            rodar_job(j, lambda: fn(lambda tipo, msg: jobs.evento(j, {"etapa": tipo, "msg": msg})))
            return {"job": j["id"]}
        with trava:
            try:
                return fn(lambda tipo, msg: None)
            except AgenteErro as e:
                raise HTTPException(502, str(e))

    @app.post("/api/imagem/analisar")
    def imagem_analisar(d: PedidoImagem):
        from ..ferramentas import visao

        ps = _caminhos_imagens(d.imagens or ([d.imagem] if d.imagem else []))
        if not ps:
            raise HTTPException(400, "envie 'imagem' (id de /api/imagens)")
        return _rodar_imagem(lambda ev: visao.analisar(serv.llm, cfg, ps, d.modo, d.pergunta, eventos=ev).dict(),
                             ps[0].name, d.job)

    @app.post("/api/imagem/pesquisar")
    def imagem_pesquisar(d: PedidoImagem):
        from ..ferramentas import visao

        ps = _caminhos_imagens([d.imagem] if d.imagem else d.imagens[:1])
        if not ps:
            raise HTTPException(400, "envie 'imagem' (id de /api/imagens)")

        def fazer(ev):
            ctx = serv.contexto(cfg.dir_dados / "area_de_trabalho")
            return visao.pesquisar(serv.llm, cfg, ctx.web, ps[0], d.foco or d.pergunta, eventos=ev).dict()

        return _rodar_imagem(fazer, ps[0].name, d.job)

    # ------------------------------------------------------------ pesquisa profunda
    @app.post("/api/pesquisa")
    def pesquisa(d: PedidoPesquisa):
        from ..agentes.profunda import PesquisaProfunda

        j = jobs.criar("pesquisa", d.pergunta)

        def fazer():
            ctx = serv.contexto(cfg.dir_dados / "area_de_trabalho")
            fmts_antes = list(cfg.profunda.formatos)
            if d.abnt and "abnt" not in cfg.profunda.formatos:
                cfg.profunda.formatos = fmts_antes + ["abnt"]
            try:
                rel = _executar_pesquisa(ctx)
            finally:
                cfg.profunda.formatos = fmts_antes
            if d.chat and serv.memoria.sessao_existe(d.chat):
                serv.memoria.adicionar_mensagem(d.chat, "user", d.pergunta)
                serv.memoria.adicionar_mensagem(d.chat, "assistant", rel.markdown)
            return {"markdown": rel.markdown, "arquivos": [Path(a).name for a in rel.arquivos],
                    "fontes": [{"n": f.n, "titulo": f.titulo, "referencia": f.referencia, "tipo": f.tipo}
                               for f in rel.fontes], "citacoes_removidas": rel.citacoes_removidas}

        def _executar_pesquisa(ctx):
            return PesquisaProfunda(ctx, lambda ev: jobs.evento(j, ev)).executar(
                d.pergunta, d.profundidade, d.largura, usar_web=d.fontes in ("web", "ambos"),
                usar_biblioteca=d.fontes in ("biblioteca", "ambos"))

        rodar_job(j, fazer)
        return {"job": j["id"]}

    @app.get("/api/relatorios")
    def relatorios():
        pasta = cfg.resolver(cfg.profunda.pasta_relatorios)
        if not pasta.exists():
            return []
        return [{"nome": p.name, "tamanho": p.stat().st_size, "modificado": p.stat().st_mtime}
                for p in sorted(pasta.iterdir(), key=lambda p: -p.stat().st_mtime) if p.is_file()]

    @app.get("/api/relatorios/{nome}")
    def relatorio(nome: str):
        p = cfg.resolver(cfg.profunda.pasta_relatorios) / Path(nome).name
        if not p.exists():
            raise HTTPException(404, "relatório não encontrado")
        return FileResponse(str(p), filename=p.name)

    # ------------------------------------------------------------ projetos
    @app.get("/api/projetos")
    def projetos():
        from ..agentes.projeto_store import ProjetoStore

        return [_info_proj(i) for i in ProjetoStore(cfg).listar()]

    def _info_proj(info, tarefas=False):
        from ..agentes.projeto_store import ProjetoStore

        d = {"id": info.id, "nome": info.nome, "objetivo": info.objetivo, "status": info.status, "fase": info.fase,
             "atualizado": info.atualizado, "erro": info.erro}
        resumo, ts = ProjetoStore(cfg).carregar_tarefas(info)
        d["total"] = len(ts)
        d["feitas"] = sum(1 for t in ts if str(t.get("status", "")).startswith("conclu"))
        if tarefas:
            d["resumo_plano"] = resumo
            d["tarefas"] = [{"titulo": t.get("titulo", ""), "status": t.get("status", ""),
                             "descricao": t.get("descricao", "")[:300]} for t in ts]
            diario = Path(info.pasta) / "DIARIO.md"
            d["diario"] = diario.read_text(encoding="utf-8")[-4000:] if diario.exists() else ""
            d["arquivos"] = sorted(str(p.relative_to(info.pasta)) for p in Path(info.pasta).rglob("*")
                                   if p.is_file() and ".agente" not in p.parts)[:200]
        return d

    @app.get("/api/projetos/{pid}")
    def projeto(pid: str):
        from ..agentes.projeto_store import ProjetoStore

        try:
            return _info_proj(ProjetoStore(cfg).carregar(pid), tarefas=True)
        except AgenteErro as e:
            raise HTTPException(404, str(e))

    @app.post("/api/projetos")
    def novo_projeto(d: PedidoProjeto):
        from ..agentes.projeto import ExecutorProjeto

        j = jobs.criar("projeto", d.objetivo)

        def fazer():
            autonomo_antes = cfg.seguranca.modo_autonomo
            cfg.seguranca.modo_autonomo = d.autonomo
            ex = ExecutorProjeto(serv, eventos=lambda t, m: jobs.evento(j, {"etapa": t, "msg": m}),
                                 confirmar=lambda a, b: False)
            try:
                info = ex.novo(d.objetivo, d.nome)
                return {"projeto": info.id, "status": info.status}
            finally:
                cfg.seguranca.modo_autonomo = autonomo_antes
                ex.fechar()

        rodar_job(j, fazer)
        return {"job": j["id"]}

    # ------------------------------------------------------------ benchmark
    @app.post("/api/benchmark")
    def benchmark(rapido: bool = True):
        from dataclasses import asdict

        from .. import benchmark as bm

        j = jobs.criar("benchmark", "benchmark")

        def fazer():
            r = bm.executar(serv, progresso=lambda s: jobs.evento(j, {"etapa": "benchmark", "msg": s}), rapido=rapido)
            bm.salvar(cfg, r)
            return asdict(r)

        rodar_job(j, fazer)
        return {"job": j["id"]}

    @app.get("/api/benchmarks")
    def benchmarks():
        from .. import benchmark as bm

        return bm.historico(cfg)

    # ------------------------------------------------------------ jobs
    # ---------------------------------------------------------------- memória de longo prazo (v0.5)
    @app.get("/api/memoria")
    def memoria_listar(escopo: str = "", q: str = "", n: int = 300):
        return {"escopos": [{"escopo": e, "n": c} for e, c in serv.memoria.escopos()],
                "itens": [x.dict() for x in serv.memoria.listar(escopo or None, n, q)]}

    @app.post("/api/memoria")
    def memoria_criar(d: NovaLembranca):
        lid = serv.memoria.lembrar(d.texto, d.tipo, d.escopo or "global", origem="usuario", marca="usuario",
                                   evidencia="escrito pelo usuário")
        if not lid:
            raise HTTPException(400, "texto curto demais")
        return serv.memoria.obter(lid).dict()

    @app.patch("/api/memoria/{lid}")
    def memoria_editar(lid: int, d: EditaLembranca):
        x = serv.memoria.atualizar(lid, d.texto, d.escopo, d.tipo, d.marca, d.fixada)
        if not x:
            raise HTTPException(404, "não encontrado")
        return x.dict()

    @app.delete("/api/memoria/{lid}")
    def memoria_apagar(lid: int):
        if not serv.memoria.esquecer(lid):
            raise HTTPException(404, "não encontrado")
        return {"ok": True}

    @app.post("/api/memoria/esquecer")
    def memoria_esquecer(escopo: str = ""):
        return {"apagados": serv.memoria.esquecer_antigos(escopo or None)}

    # ---------------------------------------------------------------- documentos (v0.5)
    @app.get("/api/documentos")
    def documentos():
        from ..biblioteca import documentos as D

        try:
            import pdfplumber  # noqa: F401
            tab = True
        except ImportError:
            tab = False
        return {"ocr": D.motor_ocr(cfg.biblioteca.ocr) or "", "ocr_config": cfg.biblioteca.ocr, "tabelas_pdf": tab,
                "reranker": cfg.biblioteca.reranker, "status": serv.indice.status(), "arquivos": serv.indice.arquivos()}

    # ---------------------------------------------------------------- kits (v0.6)
    def _pasta_kit(kit: str) -> Path:
        k = getattr(cfg.kits, kit)
        p = cfg.resolver(k.pasta_saida)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @app.get("/api/kits")
    def kits():
        from ..kits.paletas import PALETAS
        from ..kits.pixel import detectar_aseprite

        return {"pixel": {"ativo": cfg.kits.pixel.ativo, "aseprite": detectar_aseprite(cfg.kits.pixel.aseprite) or "",
                          "paletas": PALETAS, "paleta_padrao": cfg.kits.pixel.paleta_padrao},
                "abnt": {"ativo": cfg.kits.abnt.ativo, "norma_citacao": cfg.kits.abnt.norma_citacao,
                         "fonte": cfg.kits.abnt.fonte, "autor": cfg.kits.abnt.autor, "instituicao": cfg.kits.abnt.instituicao,
                         "local": cfg.kits.abnt.local}}

    @app.put("/api/kits")
    def kits_put(d: PedidoKits):
        if d.pixel is not None:
            cfg.kits.pixel.ativo = d.pixel
        if d.abnt is not None:
            cfg.kits.abnt.ativo = d.abnt
        if d.aseprite is not None:
            cfg.kits.pixel.aseprite = d.aseprite
        serv.aplicar_kits()
        if d.salvar and cfg.caminho_arquivo:
            from ..kits.cli import salvar_kits

            salvar_kits(cfg)
        return kits()

    def _png_b64(im) -> str:
        import io

        b = io.BytesIO()
        im.save(b, "PNG")
        return base64.b64encode(b.getvalue()).decode()

    @app.post("/api/pixel")
    def pixel(d: PedidoPixel):
        import io

        from ..kits import paletas as P
        from ..kits import pixel as X

        if not d.imagens_b64:
            raise HTTPException(400, "envie ao menos uma imagem")
        pasta = _pasta_kit("pixel")
        base = Path(d.nome).stem or "imagem"
        imgs = []
        for i, b in enumerate(d.imagens_b64):
            raw = base64.b64decode(b.split(",", 1)[-1])
            ext = Path(d.nome).suffix.lower() if i == 0 else ".png"
            if ext in X.EXT_ASE:
                tmp = pasta / f"_{uuid.uuid4().hex}{ext}"
                tmp.write_bytes(raw)
                try:
                    dados = X.ler_ase(tmp)
                finally:
                    tmp.unlink(missing_ok=True)
                imgs += dados["quadros"] if d.acao in ("montar", "gif", "aseprite_sheet") else dados["quadros"][:1]
            else:
                from PIL import Image

                im = Image.open(io.BytesIO(raw))
                if getattr(im, "n_frames", 1) > 1 and d.acao in ("montar", "gif"):
                    for k in range(im.n_frames):
                        im.seek(k)
                        imgs.append(im.convert("RGBA"))
                else:
                    imgs.append(im.convert("RGBA"))
        im = imgs[0]
        info, extra, saida_nome = "", {}, f"{base}-{d.acao}.png"
        try:
            if d.acao == "redimensionar":
                out = X.redimensionar(im, d.largura, d.altura, d.fator if 0 < d.fator < 1 else 0)
            elif d.acao == "upscale":
                out = X.upscale(im, int(d.fator or 4))
            elif d.acao == "remover_fundo":
                out = X.remover_fundo(im, d.cor_fundo or None, d.tolerancia)
            elif d.acao == "aplicar_paleta":
                out = X.aplicar_paleta(im, d.paleta or cfg.kits.pixel.paleta_padrao, d.dither)
            elif d.acao == "reduzir_paleta":
                out = X.reduzir_paleta(im, d.cores, d.dither)
            elif d.acao == "extrair_paleta":
                cores = X.extrair_paleta(im, 256)
                extra["paleta"] = [P.rgb_para_hex(c) for c in cores]
                P.salvar_paleta(cores, pasta / f"{base}.gpl", base)
                out = X.preview(im)
                info = f"{len(cores)} cores · {base}.gpl"
            elif d.acao == "preview":
                out = X.preview(im, int(d.fator or 0))
            elif d.acao == "fatiar":
                qs = X.fatiar(im, d.largura, d.altura)
                if not qs:
                    raise ValueError("nenhum quadro (confira largura/altura)")
                out, meta = X.montar(qs, d.colunas or len(qs))
                extra["quadros"] = len(qs)
                info = f"{len(qs)} quadros"
            elif d.acao in ("montar", "aseprite_sheet"):
                out, meta = X.montar(imgs, d.colunas, duracao_ms=d.duracao_ms)
                meta["meta"]["image"] = f"{base}-sheet.png"
                saida_nome = f"{base}-sheet.png"
                (pasta / f"{base}-sheet.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
                extra["json"] = f"{base}-sheet.json"
                info = f"{len(imgs)} quadros · {base}-sheet.json"
            elif d.acao == "gif":
                qs = imgs if len(imgs) > 1 or not (d.largura and d.altura) else X.fatiar(im, d.largura, d.altura)
                saida_nome = f"{base}.gif"
                X.gif(qs, pasta / saida_nome, d.duracao_ms, int(d.fator or 1))
                out = None
                info = f"{len(qs)} quadros"
            else:
                raise ValueError(f"ação desconhecida: {d.acao}")
        except ValueError as e:
            raise HTTPException(400, str(e))
        if out is not None:
            out.save(pasta / saida_nome)
            prev = X.preview(out) if max(out.size) < 256 else out
            img_b64 = _png_b64(prev)
            tam = f"{out.width}x{out.height}"
        else:
            img_b64 = base64.b64encode((pasta / saida_nome).read_bytes()).decode()
            tam = ""
        return {"arquivo": saida_nome, "url": f"/api/kits/arquivo/pixel/{saida_nome}", "imagem_b64": img_b64,
                "mime": "image/gif" if saida_nome.endswith(".gif") else "image/png", "tamanho": tam, "info": info, **extra}

    @app.get("/api/kits/arquivo/{kit}/{nome}")
    def kit_arquivo(kit: str, nome: str):
        from fastapi.responses import FileResponse

        if kit not in ("pixel", "abnt") or "/" in nome or "\\" in nome or nome.startswith("."):
            raise HTTPException(404, "não encontrado")
        p = _pasta_kit(kit) / nome
        if not p.is_file():
            raise HTTPException(404, "não encontrado")
        return FileResponse(p, filename=nome)

    @app.post("/api/abnt/referencias")
    def abnt_refs(d: PedidoAbntRef):
        from ..kits import abnt as A

        refs, erros = [], []
        for i in d.identificadores:
            if not i.strip():
                continue
            try:
                refs.append(A.identificar(i))
            except Exception as e:  # noqa: BLE001
                erros.append({"identificador": i, "erro": str(e)[:200]})
        A.desambiguar_anos(refs)
        norma = cfg.kits.abnt.norma_citacao
        itens = []
        for r in sorted(refs, key=A.chave_ordenacao):
            itens.append({"referencia": A.formatar_referencia(r), "citacao": A.citacao(r, norma=norma),
                          "narrativa": A.citacao(r, narrativa=True, norma=norma), "avisos": r.avisos, "dados": r.dict()})
        return {"itens": itens, "erros": erros}

    @app.post("/api/abnt/documento")
    def abnt_doc(d: PedidoAbntDoc):
        from ..kits import abnt as A

        k = cfg.kits.abnt
        refs = [A.Referencia.de_dict(x) for x in d.referencias_prontas]
        erros = []
        for i in d.referencias:
            if i.strip():
                try:
                    refs.append(A.identificar(i))
                except Exception as e:  # noqa: BLE001
                    erros.append(f"{i}: {e}")
        t = A.Trabalho(titulo=d.titulo, subtitulo=d.subtitulo, autor=d.autor or k.autor or "Autor",
                       instituicao=d.instituicao or k.instituicao, curso=d.curso or k.curso, local=d.local or k.local,
                       ano=d.ano, natureza=d.natureza, orientador=d.orientador, fonte=k.fonte)
        nome = re.sub(r"[^\w-]+", "-", A._sem_acento(d.titulo).lower()).strip("-")[:60] or "trabalho"
        destino = A.gerar_docx(t, d.texto or "# Introdução\n\n", refs, _pasta_kit("abnt") / f"{nome}-abnt.docx")
        return {"arquivo": destino.name, "url": f"/api/kits/arquivo/abnt/{destino.name}", "referencias": len(refs),
                "erros": erros}

    @app.get("/api/jobs")
    def listar_jobs():
        return jobs.listar()

    @app.get("/api/jobs/{jid}")
    def job(jid: str, desde: int = 0):
        j = jobs.obter(jid)
        if not j:
            raise HTTPException(404, "job não encontrado")
        return {**{k: v for k, v in j.items() if k != "eventos"}, "eventos": j["eventos"][desde:],
                "total_eventos": len(j["eventos"])}

    return app


def iniciar(cfg: Config, host: str = "127.0.0.1", porta: int = 8765, abrir: bool = False) -> None:
    import uvicorn

    if abrir:
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{porta}/")).start()
    uvicorn.run(criar_app(cfg), host=host, port=porta, log_level="warning")
