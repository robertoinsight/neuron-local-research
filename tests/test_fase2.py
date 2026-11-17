"""Testes da fase 2: pesquisa profunda, inhearsay, benchmark, API completa e interface."""
import base64

import pytest

from nlr.fontes import Fonte
from nlr.i18n import definir_idioma


@pytest.fixture(autouse=True)
def _pt():
    definir_idioma("pt")
    yield
    definir_idioma("pt")


# ------------------------------------------------------------ inhearsay
def test_inhearsay_marca_ordem_sem_apoio_e_condicao_perdida():
    from nlr.nucleo import inhearsay

    usuario = ["Quero um script que organize meus sprites.",
               "Antes de implementar, me mostre o plano. Só depois que eu aprovar você pode apagar as pastas antigas."]
    resumo = ("Objetivo do usuário: script que organize sprites.\n"
              "- O usuário pediu para apagar as pastas antigas.\n"
              "- O usuário aprovou publicar no GitHub.\n"
              "- O agente propôs separar por personagem.")
    anotado, v = inhearsay.anotar(resumo, usuario)
    marc = [i.texto for i in v.marcados]
    assert any("apagar" in m for m in marc)  # condição "só depois que eu aprovar" sumiu
    assert any("GitHub" in m for m in marc)  # nunca foi dito
    assert "⚠ inhearsay" in anotado and v.taxa > 0
    ok = inhearsay.verificar("- O usuário pediu um script que organize sprites.", usuario)
    assert not ok.marcados


def test_handoff_inclui_literais_e_regra(cfg):
    from nlr.memoria.armazenamento import Memoria
    from nlr.nucleo.handoff import GerenciadorHandoff

    class L:
        def chat(self, *a, **k):
            return "- O usuário pediu para apagar tudo."

    m = Memoria(cfg)
    sid = m.nova_sessao()
    m.adicionar_mensagem(sid, "user", "Se o teste passar, apague a pasta tmp.")
    m.adicionar_mensagem(sid, "assistant", "ok")
    novo = GerenciadorHandoff(cfg, m, L()).executar(sid)
    sistema = m.historico(novo)[0]["content"]
    assert "⚠ inhearsay" in sistema and "MENSAGENS LITERAIS" in sistema and "Se o teste passar" in sistema


# ------------------------------------------------------------ pesquisa profunda
def test_verificar_e_atribuir_citacoes():
    from nlr.agentes.profunda import atribuir_citacoes, limpar_texto, verificar_citacoes

    fontes = {1: Fonte(1, "web", "Aseprite", "https://a", "Aseprite é um editor de sprites e animações em pixel art."),
              2: Fonte(2, "web", "Receitas", "https://b", "Bolo de cenoura com cobertura de chocolate.")}
    txt, rem = verificar_citacoes("Aseprite edita sprites em pixel art [1][2][9].", fontes)
    assert "[1]" in txt and "[2]" not in txt and "[9]" not in txt and rem == 2
    at = atribuir_citacoes("O Aseprite é um editor de sprites e animações.", list(fontes.values()))
    assert at.endswith("[1].")
    assert limpar_texto("Resposta: frase longa o suficiente aqui. frase longa o suficiente aqui.") == \
        "frase longa o suficiente aqui."


class _LLMProf:
    perfil = None

    def __init__(self):
        from nlr.config import Config

        self.cfg = Config()

    def chat_json(self, msgs, modelo, **kw):
        nome = modelo.__name__
        if nome == "Plano":
            return modelo(subperguntas=["o que é aseprite", "preço do aseprite"])
        return modelo(lacunas=["aseprite linux"], contradicoes=["fontes divergem sobre o preço"])

    def chat(self, msgs, **kw):
        sistema = msgs[0]["content"]
        if "SUBPERGUNTA" in sistema:
            return "Aseprite é um editor de sprites e animações em pixel art [1]."
        if "introdução" in sistema.lower():
            return "INTRODUÇÃO:\nVisão geral.\nCONCLUSÃO:\nConclusão final."
        return "Aseprite é um editor de sprites e animações em pixel art [1]. Frase inventada [7]."


class _WebFalsa:
    def __init__(self):
        self.consultas = []

    def pesquisar(self, consulta, inicio=1, status=None):
        self.consultas.append(consulta)
        return [Fonte(inicio, "web", "Aseprite", "https://www.aseprite.org/",
                      "Aseprite é um editor de sprites e animações em pixel art. Custa US$ 19,99.")]


def test_pesquisa_profunda_rodadas_e_relatorio(cfg, tmp_path):
    from nlr.agentes.profunda import PesquisaProfunda

    class Ctx:
        pass

    ctx = Ctx()
    ctx.llm = _LLMProf()
    ctx.cfg = cfg
    cfg.profunda.pausa_segundos = 0
    cfg.profunda.formatos = ["md", "docx"]
    cfg.profunda.pasta_relatorios = str(tmp_path / "rel")
    ctx.web = _WebFalsa()
    ctx.evento = lambda *a: None
    eventos = []
    rel = PesquisaProfunda(ctx, eventos.append).executar("o que é o aseprite?", profundidade=2, largura=2)
    etapas = [e["etapa"] for e in eventos]
    assert etapas[0] == "inicio" and "plano" in etapas and etapas.count("revisao") == 2 and etapas[-1] == "fim"
    assert "aseprite linux" in ctx.web.consultas  # lacuna virou busca da rodada 2
    assert "[1]" in rel.markdown and "[7]" not in rel.markdown and rel.citacoes_removidas >= 1
    assert "fontes divergem" in rel.markdown and "https://www.aseprite.org/" in rel.markdown
    assert len(rel.fontes) == 1 and any(a.endswith(".docx") for a in rel.arquivos)


def test_parametros_por_perfil():
    from nlr.agentes.profunda import parametros
    from nlr.nucleo.perfil import PERFIS

    class L:
        perfil = PERFIS["grande"]

    assert parametros(L()) == (3, 6)
    assert parametros(L(), 1, 2) == (1, 2)
    L.perfil = PERFIS["pequeno"]
    assert parametros(L()) == (1, 3)


# ------------------------------------------------------------ benchmark
def test_benchmark_recomendacao():
    from nlr.benchmark import Resultado, recomendar
    from nlr.nucleo.hardware import Hardware

    hw = Hardware("x", 24, 8, "RTX", 8)
    r = Resultado("m", "ollama", 8192, "medio", {}, tokens_por_segundo=30, json_primeira=1, json_com_correcao=1,
                  ferramentas=1)
    assert recomendar(r, hw)["perfil"] == "grande" and recomendar(r, hw)["contexto_tokens"] == 16384
    r2 = Resultado("m", "ollama", 4096, "medio", {}, tokens_por_segundo=3, json_com_correcao=0.4, ferramentas=0)
    rec = recomendar(r2, hw)
    assert rec["perfil"] == "pequeno" and rec["contexto_tokens"] == 4096 and rec["dica"]


def test_benchmark_rapido_com_servidor_falso(cfg, srv):
    from nlr import benchmark as bm
    from nlr.servicos import Servicos

    serv = Servicos(cfg)
    try:
        r = bm.executar(serv, rapido=True)
        p = bm.salvar(cfg, r)
        assert p.exists() and r.tokens_por_segundo > 0 and bm.historico(cfg)[0]["modelo"] == "modelo-falso"
    finally:
        serv.fechar()


# ------------------------------------------------------------ API + interface
def test_api_fase2(cfg, srv):
    from fastapi.testclient import TestClient

    from nlr.api.app import criar_app
    from nlr.servicos import Servicos

    cfg.memoria.extrair_automaticamente = False
    serv = Servicos(cfg)
    try:
        c = TestClient(criar_app(cfg, serv))
        html = c.get("/").text
        assert "Neuron Local Research" in html and "cdn" not in html.lower()
        for a in ("/static/app.js", "/static/style.css", "/static/vendor/marked.min.js",
                  "/static/vendor/purify.min.js", "/static/vendor/highlight.min.js"):
            assert c.get(a).status_code == 200, a
        pt, en = c.get("/api/i18n/pt").json(), c.get("/api/i18n/en").json()
        assert set(pt) == set(en) and en["novo_chat"] == "New chat"
        sid = c.post("/api/chats", json={"titulo": "teste"}).json()["id"]
        assert c.patch(f"/api/chats/{sid}", json={"titulo": "Renomeado"}).json()["titulo"] == "Renomeado"
        c.post(f"/api/chats/{sid}/mensagens", json={"texto": "palavra-unica-xyz", "modo": "conversa"})
        assert [x["id"] for x in c.get("/api/chats?q=palavra-unica-xyz").json()] == [sid]
        up = c.post("/api/upload", json={"nome": "nota.txt", "destino": "chat",
                                         "dados_b64": base64.b64encode("conteúdo do anexo".encode()).decode()}).json()
        assert "conteúdo do anexo" in up["texto"]
        conf = c.get("/api/configuracoes").json()
        assert "profunda" in conf["modos"] and conf["backend"] == "ollama"
        assert c.put("/api/configuracoes", json={"idioma": "en", "salvar": False}).json()["idioma"] == "en"
        assert c.get("/api/projetos").status_code == 200 and c.get("/api/relatorios").status_code == 200
        assert c.delete(f"/api/chats/{sid}").json()["ok"] and c.get(f"/api/chats/{sid}").status_code == 404
        j = c.post("/api/benchmark?rapido=true").json()["job"]
        import time

        for _ in range(100):
            st = c.get(f"/api/jobs/{j}").json()
            if st["estado"] != "rodando":
                break
            time.sleep(0.1)
        assert st["estado"] == "concluido", st
    finally:
        definir_idioma("pt")
        serv.fechar()
