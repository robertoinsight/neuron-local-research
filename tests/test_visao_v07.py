"""v0.7: visão completa — detecção do modelo de visão, imagens no chat, API, CLI, busca reversa opcional."""
import base64
import io

import pytest
from PIL import Image

from nlr.fontes import Fonte
from nlr.servicos import Servicos


def _png_b64(tam=(40, 30), cor=(200, 40, 40)) -> str:
    b = io.BytesIO()
    Image.new("RGB", tam, cor).save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def _lmstudio(cfg, srv, v0, v1=None):
    cfg.modelo.backend = "lmstudio"
    srv.lmstudio_v0 = v0
    srv.lmstudio_v1 = v1


# ------------------------------------------------------------------ detecção (descoberta)
def test_descoberta_lmstudio_vlm_e_capabilities(cfg, srv):
    from nlr.nucleo import descoberta

    srv.lmstudio_v0 = [
        {"id": "qwen2.5-vl-7b-instruct", "type": "vlm", "state": "loaded", "max_context_length": 32768},
        {"id": "gemma-4-12b", "type": "llm", "state": "not-loaded", "max_context_length": 131072},
        {"id": "nex-n2-mini", "type": "llm", "state": "not-loaded"},
        {"id": "text-embedding-nomic-embed-text-v1.5", "type": "embeddings", "state": "not-loaded"},
    ]
    srv.lmstudio_v1 = [{"key": "gemma-4-12b", "type": "llm", "capabilities": {"vision": True}}]
    ms = {m.id: m for m in descoberta.listar("lmstudio", srv.url)}
    assert ms["qwen2.5-vl-7b-instruct"].visao and ms["qwen2.5-vl-7b-instruct"].carregado
    assert ms["gemma-4-12b"].visao  # visão vinda do /api/v1 (capabilities.vision)
    assert not ms["nex-n2-mini"].visao and ms["nex-n2-mini"].visao_conhecida
    assert ms["text-embedding-nomic-embed-text-v1.5"].tipo == "embeddings"


def test_descoberta_ollama_e_llamacpp(monkeypatch):
    from nlr.nucleo import descoberta

    def falso(url, timeout=5.0, metodo="get", **kw):
        if url.endswith("/api/tags"):
            return {"models": [{"name": "gemma3:4b", "details": {"family": "gemma3", "parameter_size": "4.3B"},
                                "capabilities": ["completion", "vision"]},
                               {"name": "qwen2.5:1.5b", "details": {"family": "qwen2"}, "capabilities": ["completion", "tools"]}]}
        if url.endswith("/api/ps"):
            return {"models": []}
        if url.endswith("/props"):
            return {"default_generation_settings": {"n_ctx": 8192}, "modalities": {"vision": True}}
        if url.endswith("/models"):
            return {"data": [{"id": "qwen2.5-vl-3b-instruct"}]}
        raise AssertionError(url)

    monkeypatch.setattr(descoberta, "_get", falso)
    ms = {m.id: m for m in descoberta.listar("ollama", "http://x:11434/v1")}
    assert ms["gemma3:4b"].visao and not ms["qwen2.5:1.5b"].visao and ms["qwen2.5:1.5b"].visao_conhecida
    (m,) = descoberta.listar("llamacpp", "http://x:8080/v1")
    assert m.visao and m.visao_conhecida and m.contexto_carregado == 8192


# ------------------------------------------------------------------ estado do modelo de visão
def test_estado_visao_usa_chat_com_visao(cfg, srv):
    from nlr.ferramentas.visao import estado_visao

    srv.modelos.append("vlm-falso")
    try:
        _lmstudio(cfg, srv, [{"id": "vlm-falso", "type": "vlm", "state": "loaded"},
                             {"id": "embed-falso", "type": "embeddings", "state": "loaded"}])
        cfg.modelo.modelo_chat = "vlm-falso"
        s = Servicos(cfg)
        e = estado_visao(s.llm, cfg)
        assert e.ok and e.modelo == "vlm-falso" and e.tem_visao is True and e.origem == "modelo_chat"
    finally:
        srv.modelos.remove("vlm-falso")


def test_estado_visao_escolhe_vlm_carregado_quando_chat_nao_tem(cfg, srv):
    from nlr.ferramentas.visao import estado_visao

    _lmstudio(cfg, srv, [{"id": "modelo-falso", "type": "llm", "state": "loaded"},
                         {"id": "qwen2.5-vl-7b", "type": "vlm", "state": "loaded"}])
    e = estado_visao(Servicos(cfg).llm, cfg)
    assert e.ok and e.modelo == "qwen2.5-vl-7b" and e.origem == "auto" and "qwen2.5-vl-7b" in e.avisos[0]


def test_estado_visao_erros_claros(cfg, srv):
    from nlr.ferramentas.visao import estado_visao
    from nlr.i18n import definir_idioma

    _lmstudio(cfg, srv, [{"id": "modelo-falso", "type": "llm", "state": "loaded"}])
    e = estado_visao(Servicos(cfg).llm, cfg)
    assert not e.ok and "olho" in e.erro and "modelo_visao" in e.erro  # nenhum modelo de visão
    cfg.modelo.modelo_visao = "modelo-falso"
    e = estado_visao(Servicos(cfg).llm, cfg)
    assert not e.ok and "não tem visão" in e.erro
    cfg.modelo.modelo_visao = "nao-existe"
    assert "não existe" in estado_visao(Servicos(cfg).llm, cfg).erro
    definir_idioma("en")
    try:
        cfg.modelo.modelo_visao = "modelo-falso"
        assert "has no vision" in estado_visao(Servicos(cfg).llm, cfg).erro
    finally:
        definir_idioma("pt")


def test_estado_visao_nao_carregado_avisa(cfg, srv):
    from nlr.ferramentas.visao import estado_visao

    _lmstudio(cfg, srv, [{"id": "modelo-falso", "type": "llm", "state": "loaded"},
                         {"id": "gemma-3-12b", "type": "vlm", "state": "not-loaded"}])
    cfg.modelo.modelo_visao = "gemma-3-12b"
    e = estado_visao(Servicos(cfg).llm, cfg)
    assert e.ok and e.carregado is False and any("não está carregado" in a for a in e.avisos)


def test_analise_falha_com_mensagem_quando_sem_visao(cfg, srv, tmp_path):
    from nlr.erros import AgenteErro
    from nlr.ferramentas import visao

    Image.new("RGB", (50, 50)).save(tmp_path / "a.png")
    _lmstudio(cfg, srv, [{"id": "modelo-falso", "type": "llm", "state": "loaded"}])
    with pytest.raises(AgenteErro, match="nlr imagem status"):
        visao.analisar(Servicos(cfg).llm, cfg, [tmp_path / "a.png"], "geral")


# ------------------------------------------------------------------ análise e utilidades
def test_minucioso_em_etapas_e_antirepeticao(cfg, srv, tmp_path):
    from nlr.ferramentas import visao

    Image.new("RGB", (2000, 1200), (10, 120, 30)).save(tmp_path / "grande.jpg")
    r = visao.analisar(Servicos(cfg).llm, cfg, [tmp_path / "grande.jpg"], "minucioso")
    assert r.vistas == 5 and r.modo == "minucioso"
    chats = [q for p, q in srv.requisicoes if p.endswith("/chat/completions")]
    assert len(chats) == 5  # 4 recortes + análise final
    assert "NOTAS DOS QUADRANTES" in chats[-1]["messages"][-1]["content"][0]["text"]
    assert chats[0]["repeat_penalty"] == 1.12  # parâmetro anti-laço enviado ao servidor
    assert visao.limpar_repeticoes("- pelos claros no pescoço\n- pelos claros no pescoço\n```\nx\n```") == \
        "- pelos claros no pescoço\n```\nx\n```"


def test_pixel_art_tem_medidas_objetivas(cfg, srv, tmp_path):
    from nlr.ferramentas import visao

    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for x in range(4, 12):
        img.putpixel((x, 8), (255, 0, 0, 255))
    img.putpixel((1, 1), (0, 255, 0, 255))  # pixel órfão
    img.save(tmp_path / "s.png")
    assert "1 pixels isolados" in visao.medidas_pixel_art(img)
    r = visao.analisar(Servicos(cfg).llm, cfg, [tmp_path / "s.png"])  # sem modo: sprite vira revisão de pixel art
    assert r.modo == "pixel"
    ultimo = [q for p, q in srv.requisicoes if p.endswith("/chat/completions")][-1]
    assert "MEDIDAS OBJETIVAS" in ultimo["messages"][-1]["content"][0]["text"]
    r = visao.analisar(Servicos(cfg).llm, cfg, [tmp_path / "s.png"], "geral")  # modo explícito é respeitado
    assert r.modo == "geral"


def test_varias_imagens_numa_chamada(cfg, srv, tmp_path):
    from nlr.ferramentas import visao

    for n in ("a", "b"):
        Image.new("RGB", (300, 200)).save(tmp_path / f"{n}.png")
    r = visao.analisar(Servicos(cfg).llm, cfg, [tmp_path / "a.png", tmp_path / "b.png"], "geral", "qual a diferença?")
    assert r.vistas == 2 and "2 vista(s)" in r.texto


# ------------------------------------------------------------------ pesquisa e busca reversa
def _web_falsa(monkeypatch, alvo, vistas):
    def falso(consulta, status=None, inicio=1):
        vistas.append(consulta)
        return [Fonte(n=0, tipo="web", titulo=f"Sobre {consulta}", referencia=f"https://ex.org/{len(vistas)}", texto="...")]

    monkeypatch.setattr(alvo, "pesquisar", falso)


def test_pesquisar_sintetiza_com_fontes(cfg, srv, tmp_path, monkeypatch):
    from nlr.ferramentas import visao
    from nlr.web.busca import PesquisaWeb

    Image.new("RGB", (300, 200)).save(tmp_path / "g.jpg")
    web, vistas = PesquisaWeb(cfg), []
    _web_falsa(monkeypatch, web, vistas)
    r = visao.pesquisar(Servicos(cfg).llm, cfg, web, tmp_path / "g.jpg", "que raça")
    assert vistas == ["gato laranja teclado"] and r.fontes[0].n == 1 and not r.reversa
    assert "um gato laranja sobre um teclado" in r.texto and "Buscas feitas" in r.texto


def test_busca_reversa_desligada_e_travas(cfg, srv, tmp_path, monkeypatch):
    from nlr.ferramentas import visao
    from nlr.web.busca import PesquisaWeb

    Image.new("RGB", (300, 200)).save(tmp_path / "g.jpg")
    web, vistas = PesquisaWeb(cfg), []
    _web_falsa(monkeypatch, web, vistas)
    chamou = []
    monkeypatch.setattr(visao, "busca_reversa_serpapi", lambda *a, **k: chamou.append(1) or [])
    llm = Servicos(cfg).llm
    assert cfg.visao.busca_reversa.provedor == "desligado"  # padrão: nada sai do PC
    visao.pesquisar(llm, cfg, web, tmp_path / "g.jpg")
    cfg.visao.busca_reversa.provedor = "serpapi"
    r = visao.pesquisar(llm, cfg, web, tmp_path / "g.jpg")
    assert any("consentimento_envio" in a for a in r.avisos)
    cfg.visao.busca_reversa.consentimento_envio = True
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    r = visao.pesquisar(llm, cfg, web, tmp_path / "g.jpg")
    assert any("SERPAPI_API_KEY" in a for a in r.avisos)
    monkeypatch.setenv("SERPAPI_API_KEY", "chave-teste")
    r = visao.pesquisar(llm, cfg, web, tmp_path / "g.jpg", "PESSOAS-TESTE")
    assert any("rosto" in a for a in r.avisos) and not chamou  # pessoas em destaque: nunca envia
    visao.pesquisar(llm, cfg, web, tmp_path / "g.jpg")
    assert chamou == [1]


def test_serpapi_lens_monta_fontes(cfg, tmp_path, monkeypatch):
    import requests

    from nlr.ferramentas import visao

    Image.new("RGB", (3000, 2000), (1, 2, 3)).save(tmp_path / "f.jpg")
    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    enviado = {}

    class R:
        def __init__(self, d):
            self._d = d

        def raise_for_status(self):
            pass

        def json(self):
            return self._d

    def post(url, files=None, data=None, timeout=0):
        enviado["bytes"] = len(files["image"][1])
        assert url == "https://serpapi.com/image" and data["api_key"] == "k"
        return R({"image_id": "abc"})

    def get(url, params=None, timeout=0):
        assert params["engine"] == "google_lens" and params["image_id"] == "abc"
        return R({"visual_matches": [{"title": "Girassol", "link": "https://ex.org/girassol", "source": "ex.org"}],
                  "knowledge_graph": [{"title": "Helianthus annuus", "link": "https://ex.org/kg", "subtitle": "planta"}]})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", get)
    fs = visao.busca_reversa_serpapi(tmp_path / "f.jpg", cfg)
    assert enviado["bytes"] <= 500_000  # limite da SerpApi
    assert [f.referencia for f in fs] == ["https://ex.org/kg", "https://ex.org/girassol"]


# ------------------------------------------------------------------ chat, API e CLI
def test_chat_com_imagem_guarda_marcador(cfg, srv, tmp_path):
    from nlr.agentes.chat import SessaoChat

    cfg.memoria.extrair_automaticamente = False
    Image.new("RGB", (300, 200)).save(tmp_path / "abcdef123456.png")
    s = Servicos(cfg)
    ch = SessaoChat(s)
    r = ch.responder_imagem("o que tem aqui?", [tmp_path / "abcdef123456.png"], marcadores=["abcdef123456.png"])
    assert r.rota == "imagem" and "vista" in r.texto
    hist = s.memoria.historico(ch.id)
    assert hist[0]["content"] == "o que tem aqui?\n[imagem:abcdef123456.png]"
    r = ch.responder_imagem("", [tmp_path / "abcdef123456.png"], acao="texto")
    assert s.memoria.historico(ch.id)[2]["content"].startswith("[Ler texto]")


def test_api_imagens_visao_e_chat(cfg, srv):
    import json

    from fastapi.testclient import TestClient

    from nlr.api.app import criar_app

    cfg.memoria.extrair_automaticamente = False
    serv = Servicos(cfg)
    c = TestClient(criar_app(cfg, serv))
    r = c.post("/api/imagens", json={"nome": "foto.png", "dados_b64": _png_b64()}).json()
    assert r["largura"] == 40 and r["miniatura"].startswith("data:image/png;base64,")
    iid = r["id"]
    assert c.get(f"/api/imagens/{iid}").status_code == 200
    assert c.get("/api/imagens/..%2Fconfig.yaml").status_code == 404
    assert c.post("/api/imagens", json={"nome": "x.png", "dados_b64": base64.b64encode(b"nao-e-imagem").decode()}).status_code == 415
    v = c.get("/api/visao").json()
    assert "ok" in v and v["busca_reversa"]["provedor"] == "desligado" and v["links_manuais"] is True
    a = c.post("/api/imagem/analisar", json={"imagem": iid, "modo": "geral"}).json()
    assert a["vistas"] == 1 and a["modo"] == "geral"
    p = c.post("/api/imagem/pesquisar", json={"imagem": iid, "foco": "o que é"})
    assert p.status_code == 200 and "Buscas feitas" in p.json()["texto"]
    j = c.post("/api/imagem/analisar", json={"imagem": iid, "modo": "texto", "job": True}).json()["job"]
    import time

    for _ in range(100):
        st = c.get(f"/api/jobs/{j}").json()
        if st["estado"] != "rodando":
            break
        time.sleep(0.05)
    assert st["estado"] == "concluido" and st["resultado"]["modo"] == "texto"
    # upload antigo (📎 Anexar) com imagem vira imagem de visão
    up = c.post("/api/upload", json={"nome": "tela.png", "destino": "chat", "dados_b64": _png_b64()}).json()
    assert up["tipo"] == "imagem" and up["id"].endswith(".png")
    sid = c.post("/api/chats", json={}).json()["id"]
    resp = c.post(f"/api/chats/{sid}/mensagens", json={"texto": "", "imagens": [iid], "acao_imagem": "minucioso",
                                                       "stream": True})
    eventos = [ln for ln in resp.text.splitlines() if ln.startswith("event:")]
    assert "event: fim" in eventos
    fim = json.loads(resp.text.split("event: fim\ndata: ")[1].split("\n")[0])
    assert fim["rota"] == "imagem"
    msgs = c.get(f"/api/chats/{sid}").json()["mensagens"]
    assert f"[imagem:{iid}]" in msgs[0]["content"]
    assert c.post(f"/api/chats/{sid}/mensagens", json={"texto": "x", "imagens": ["000000000000.png"]}).status_code == 404
    i18 = c.get("/api/i18n/en").json()
    assert i18["acao_pesquisar"] == "Search the web by image"
    serv.fechar()


def test_cli_imagem(cfg, srv, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from nlr.cli import app, comando_traduzido

    monkeypatch.chdir(tmp_path)
    p = tmp_path / "config.yaml"
    cfg.salvar(p)
    Image.new("RGB", (300, 200)).save(tmp_path / "foto.png")
    R = CliRunner()
    r = R.invoke(app, ["--config", str(p), "imagem", "analisar", str(tmp_path / "foto.png"), "--modo", "geral",
                       "--salvar", str(tmp_path / "a.md")])
    assert r.exit_code == 0, r.output
    assert "Visão geral" in (tmp_path / "a.md").read_text(encoding="utf-8")
    r = R.invoke(app, ["--config", str(p), "imagem", "status"])
    assert "Modelo de visão" in r.output
    r = R.invoke(app, ["--config", str(p), "imagem", "analisar", str(tmp_path / "nada.png")])
    assert r.exit_code == 1 and "não encontrada" in r.output
    from click.testing import CliRunner as ClickRunner

    en = ClickRunner().invoke(comando_traduzido("en"), ["imagem", "pesquisar", "--help"])
    assert "what you want to find out" in en.output
