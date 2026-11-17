"""Testes da fase 1 do NLR: i18n, descoberta, perfis, roteador, anti-loop, handoff e API."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nlr.i18n import definir_idioma, t
from nlr.nucleo import descoberta, perfil, roteador_ferramentas
from nlr.nucleo.descoberta import InfoModelo
from nlr.nucleo.guarda import GuardaLoop


@pytest.fixture(autouse=True)
def _pt():
    definir_idioma("pt")
    yield
    definir_idioma("pt")


# ------------------------------------------------------------ i18n
def test_i18n_troca_idioma():
    assert "português" in t("prompt.idioma")
    definir_idioma("en-US")
    assert "English" in t("prompt.idioma")
    assert "bogus" in t("modelo.sem_chat", backend="bogus")
    definir_idioma("xx")  # desconhecido cai para pt
    assert "português" in t("prompt.idioma")


def test_i18n_chaves_iguais():
    from nlr.i18n.textos import EN, PT

    assert set(PT) == set(EN)


# ------------------------------------------------------------ descoberta
@pytest.mark.parametrize("nome,b", [("qwen3.5-9b", 9), ("gemma-4-e4b-it", 4), ("qwen2.5:0.5b", 0.5),
                                    ("mixtral-8x7b", 56), ("llama-3.1-70b-instruct", 70), ("phi", 0)])
def test_parametros_do_nome(nome, b):
    assert descoberta.parametros_do_nome(nome) == b


def test_escolher_prefere_carregado():
    ms = [InfoModelo("gemma-12b", carregado=False, parametros_b=12),
          InfoModelo("qwen-4b", carregado=True, contexto_carregado=8192, parametros_b=4),
          InfoModelo("text-embedding-nomic", tipo="embeddings")]
    e = descoberta.escolher(ms, "auto", "auto", "lmstudio")
    assert e.chat == "qwen-4b" and e.embeddings == "text-embedding-nomic" and e.contexto == 8192


def test_escolher_sem_carregado_avisa(monkeypatch):
    from nlr.nucleo import hardware

    monkeypatch.setattr(hardware, "detectar", lambda forcar=False: hardware.Hardware("x", 24, 8, "RTX", 8))
    ms = [InfoModelo("gemma-70b", parametros_b=70), InfoModelo("gemma-e4b", parametros_b=4),
          InfoModelo("qwen-9b", parametros_b=9), InfoModelo("nomic-embed-text-v1.5", tipo="embeddings")]
    e = descoberta.escolher(ms, "auto", "auto")
    assert e.chat == "qwen-9b"  # o maior que cabe em 8 GB VRAM + 24 GB RAM
    assert any("escolhi" in a for a in e.avisos)


def test_escolher_nome_inexistente():
    e = descoberta.escolher([InfoModelo("a-7b")], "b-7b", "")
    assert any("não existe" in a for a in e.avisos)
    e = descoberta.escolher([InfoModelo("qwen2.5:0.5b:latest")], "qwen2.5:0.5b", "")
    assert not e.avisos


def test_escolher_sem_chat():
    from nlr.erros import AgenteErro

    with pytest.raises(AgenteErro):
        descoberta.escolher([InfoModelo("bge-m3", tipo="embeddings")], "auto", "auto", "lmstudio")


class _LMStudioFalso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api/v0/models":
            corpo = {"data": [
                {"id": "gemma4-12b", "type": "llm", "state": "not-loaded", "max_context_length": 131072},
                {"id": "gemma-4-e4b", "type": "vlm", "state": "loaded", "max_context_length": 131072,
                 "loaded_context_length": 8192},
                {"id": "text-embedding-nomic-embed-text-v1.5", "type": "embeddings", "state": "not-loaded",
                 "max_context_length": 2048}]}
        elif self.path == "/v1/models":
            corpo = {"data": [{"id": "gemma4-12b"}, {"id": "gemma-4-e4b"}, {"id": "text-embedding-nomic-embed-text-v1.5"}]}
        else:
            self.send_response(404)
            self.end_headers()
            return
        b = json.dumps(corpo).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


@pytest.fixture
def lmstudio():
    s = HTTPServer(("127.0.0.1", 0), _LMStudioFalso)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}/v1"
    s.shutdown()


def test_lmstudio_auto_usa_carregado_e_contexto_real(lmstudio):
    from nlr.config import Config
    from nlr.llm.cliente import ClienteLLM

    c = Config()
    c.modelo.backend, c.modelo.base_url = "lmstudio", lmstudio
    c.modelo.modelo_chat, c.modelo.modelo_embeddings = "auto", "auto"
    avisos = []
    llm = ClienteLLM(c, eventos=avisos.append)
    info = llm.preparar()
    assert info["modelo_chat"] == "gemma-4-e4b"  # o carregado, não o primeiro da lista
    assert info["modelo_embeddings"] == "text-embedding-nomic-embed-text-v1.5"
    assert info["contexto_tokens"] == 8192
    assert info["perfil"]["nome"] == "pequeno"
    assert any("8192" in a for a in avisos)


# ------------------------------------------------------------ perfis
def test_perfis():
    assert perfil.classificar(0.5) == "pequeno"
    assert perfil.classificar(9) == "medio"
    assert perfil.classificar(32) == "grande"
    assert perfil.classificar(32, contexto=4096) == "pequeno"
    assert perfil.obter("grande").max_ferramentas > perfil.obter("pequeno").max_ferramentas
    assert perfil.max_tokens_para(perfil.obter("grande"), 4096) == 1024


# ------------------------------------------------------------ roteador
class _F:
    def __init__(self, nome, desc, grupos):
        self.nome, self.descricao, self.grupos = nome, desc, set(grupos)


def test_roteador_escolhe_relevantes():
    fs = [_F("ler_arquivo", "Lê um arquivo de texto", ["arquivos"]),
          _F("escrever_arquivo", "Escreve um arquivo", ["arquivos"]),
          _F("rodar_comando", "Executa um comando no terminal", ["codigo"]),
          _F("pesquisar_web", "Pesquisa na internet", ["pesquisa"]),
          _F("lembrar", "Guarda um fato na memória", ["memoria"]),
          _F("calcular", "Calcula expressões", ["util"])]
    sel = roteador_ferramentas.selecionar(fs, "pesquise na internet as notícias de hoje", 3)
    assert len(sel) == 3 and sel[0].nome == "pesquisar_web"
    sel = roteador_ferramentas.selecionar(fs, "rode os testes python do projeto", 2)
    assert sel[0].nome == "rodar_comando"
    assert roteador_ferramentas.selecionar(fs, "x", 10) == fs


# ------------------------------------------------------------ anti-loop
def test_guarda_repeticao_e_parada():
    g = GuardaLoop()
    assert g.antes("ler", {"a": 1}).acao == "ok"
    assert g.antes("ler", {"a": 1}).acao == "avisar"
    assert g.antes("ler", {"a": 1}).acao == "parar"


def test_guarda_oscilacao_e_erros():
    g = GuardaLoop()
    res = [g.antes("a" if i % 2 == 0 else "b", {}).acao for i in range(6)]
    assert res[-1] == "avisar"
    g2 = GuardaLoop(max_erros=2)
    assert g2.depois("ERRO: x") is None
    assert "erros seguidos" in g2.depois("ERRO: y")


def test_erro_ferramenta_tem_exemplo():
    from nlr.ferramentas.registro import REGISTRO_PADRAO, carregar_embutidas

    carregar_embutidas()
    nome = "ler_arquivo" if REGISTRO_PADRAO.obter("ler_arquivo") else REGISTRO_PADRAO.nomes()[0]
    msg = REGISTRO_PADRAO.executar(nome, {"nao_existe": 1}, None)
    assert "Corrija" in msg and '"ferramenta"' in msg
    assert "não existe" in REGISTRO_PADRAO.executar("ferramenta_x", {}, None)


# ------------------------------------------------------------ handoff
class _LLMFalso:
    def __init__(self, falhar=False):
        self.falhar = falhar
        self.chamadas = 0

    def chat(self, msgs, **kw):
        from nlr.erros import AgenteErro

        self.chamadas += 1
        if self.falhar:
            raise AgenteErro("fora do ar")
        return "Objetivo: jogo de pixel art. Próximos passos: spritesheet."


def _mem(cfg):
    from nlr.memoria.armazenamento import Memoria

    return Memoria(cfg)


def test_handoff_cria_chat_ligado(cfg):
    from nlr.nucleo.handoff import GerenciadorHandoff

    cfg.modelo.contexto_tokens = 2048
    cfg.modelo.max_tokens = 256
    m = _mem(cfg)
    sid = m.nova_sessao()
    h = GerenciadorHandoff(cfg, m, _LLMFalso())
    m.adicionar_mensagem(sid, "user", "olá")
    m.adicionar_mensagem(sid, "assistant", "oi")
    assert not h.precisa(sid)
    for i in range(20):
        m.adicionar_mensagem(sid, "user", f"pedido {i} " + "texto longo " * 40)
        m.adicionar_mensagem(sid, "assistant", "resposta " * 40)
    assert h.precisa(sid)
    novo = h.executar(sid)
    assert m.pai_sessao(novo) == sid and m.filho_sessao(sid) == novo
    assert m.cadeia_sessoes(novo) == [sid, novo]
    hist = m.historico(novo)
    assert hist[0]["role"] == "system" and "pixel art" in hist[0]["content"]
    assert not h.precisa(novo)


def test_handoff_sem_modelo_usa_extrativo(cfg):
    from nlr.nucleo.handoff import GerenciadorHandoff

    m = _mem(cfg)
    sid = m.nova_sessao()
    m.adicionar_mensagem(sid, "user", "quero um jogo de nave")
    m.adicionar_mensagem(sid, "assistant", "ok")
    novo = GerenciadorHandoff(cfg, m, _LLMFalso(falhar=True)).executar(sid)
    assert "jogo de nave" in m.historico(novo)[0]["content"]


def test_sessao_chat_faz_handoff(cfg, srv):
    from nlr.agentes.chat import SessaoChat
    from nlr.servicos import Servicos

    cfg.modelo.contexto_tokens = 2048
    cfg.modelo.contexto_auto = False
    cfg.modelo.max_tokens = 200
    cfg.memoria.extrair_automaticamente = False
    serv = Servicos(cfg)
    try:
        s = SessaoChat(serv)
        primeiro = s.id
        for i in range(12):
            serv.memoria.adicionar_mensagem(s.id, "user", "contexto " * 60)
            serv.memoria.adicionar_mensagem(s.id, "assistant", "resposta " * 60)
        r = s.responder("continue, por favor", modo="conversa")
        assert r.sessao != primeiro and serv.memoria.pai_sessao(r.sessao) == primeiro
        assert any("chat novo" in a for a in r.avisos)
    finally:
        serv.fechar()


# ------------------------------------------------------------ API
def test_api(cfg, srv):
    from fastapi.testclient import TestClient

    from nlr.api.app import criar_app
    from nlr.servicos import Servicos

    cfg.memoria.extrair_automaticamente = False
    serv = Servicos(cfg)
    try:
        c = TestClient(criar_app(cfg, serv))
        assert c.get("/api/saude").json()["servidor_ok"] is True
        assert c.get("/api/modelos").json()["modelo_chat"] == "modelo-falso"
        sid = c.post("/api/chats", json={}).json()["id"]
        r = c.post(f"/api/chats/{sid}/mensagens", json={"texto": "oi", "modo": "conversa"}).json()
        assert r["texto"] and r["sessao"] == sid
        with c.stream("POST", f"/api/chats/{sid}/mensagens", json={"texto": "oi de novo", "modo": "conversa",
                                                                  "stream": True}) as resp:
            corpo = "".join(resp.iter_text())
        assert "event: token" in corpo and "event: fim" in corpo
        assert len(c.get(f"/api/chats/{sid}").json()["mensagens"]) == 4
        assert c.put("/api/idioma", json={"idioma": "en"}).json()["idioma"] == "en"
        assert c.get("/api/chats/inexistente").status_code == 404
    finally:
        definir_idioma("pt")
        serv.fechar()
