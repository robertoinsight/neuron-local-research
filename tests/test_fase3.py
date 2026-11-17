"""Testes da fase 3 (v0.5): status do modelo, documentos difíceis, RAG estrutural, memória por projeto, i18n."""
import time

import pytest

from nlr.i18n import definir_idioma


@pytest.fixture(autouse=True)
def _pt():
    definir_idioma("pt")
    yield
    definir_idioma("pt")


# ------------------------------------------------------------ 1) bug "não carregado"
def test_preparar_rele_estado_do_servidor(cfg, monkeypatch):
    from nlr.llm.cliente import ClienteLLM
    from nlr.nucleo import descoberta
    from nlr.nucleo.descoberta import InfoModelo

    estado = {"carregado": False, "n": 0}

    def listar(backend, base_url, api_key=""):
        estado["n"] += 1
        return [InfoModelo(id="modelo-falso", tipo="chat", carregado=estado["carregado"], parametros_b=1.5),
                InfoModelo(id="embed-falso", tipo="embeddings")]

    monkeypatch.setattr(descoberta, "listar", listar)
    llm = ClienteLLM(cfg)
    a = llm.preparar()
    assert not next(m for m in a["modelos"] if m["id"] == "modelo-falso")["carregado"]
    estado["carregado"] = True  # o modelo carregou depois (1ª resposta)
    b = llm.preparar()
    assert next(m for m in b["modelos"] if m["id"] == "modelo-falso")["carregado"], "estado ficava em cache (bug v0.4)"
    assert "ultima_resposta" in b and estado["n"] >= 2


def test_ui_tem_estado_sob_demanda_e_atualiza_apos_resposta():
    from pathlib import Path

    import nlr.api as api
    from nlr.i18n.ui import EN, PT

    js = (Path(api.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert "setTimeout(carregarModelos" in js and "ultima_resposta" in js and "sob_demanda" in js
    assert PT["sob_demanda"] and EN["sob_demanda"]


# ------------------------------------------------------------ 2) documentos difíceis
def _pdf_escaneado(caminho, texto="RELATORIO ANUAL 2025 RECEITA 4500"):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1400, 400), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", 64)
    except OSError:
        try:
            f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 64)
        except OSError:
            f = ImageFont.load_default()
    d.text((40, 150), texto, fill="black", font=f)
    img.save(caminho, "PDF", resolution=150)
    return caminho


def test_deteccao_pagina_escaneada_sem_ocr(tmp_path, monkeypatch):
    from nlr.biblioteca import carregadores as C
    from nlr.biblioteca import documentos as D
    from nlr.erros import AgenteErro

    assert D.pagina_parece_escaneada("", True) and not D.pagina_parece_escaneada("texto " * 30, True)
    assert not D.pagina_parece_escaneada("", False)
    pdf = _pdf_escaneado(tmp_path / "scan.pdf")
    monkeypatch.setitem(C.OPCOES, "ocr", "nenhum")
    C.AVISOS.clear()
    with pytest.raises(AgenteErro, match="escaneado"):
        C.carregar_arquivo(pdf)
    assert any("escaneada" in a for a in C.AVISOS)


def test_ocr_pdf_escaneado(tmp_path, monkeypatch):
    from nlr.biblioteca import carregadores as C
    from nlr.biblioteca import documentos as D

    if not D.motor_ocr("auto"):
        pytest.skip("sem motor de OCR instalado (pip install rapidocr-onnxruntime)")
    pdf = _pdf_escaneado(tmp_path / "scan.pdf")
    monkeypatch.setitem(C.OPCOES, "ocr", "auto")
    segs = C.carregar_arquivo(pdf)
    txt = " ".join(s.texto for s in segs).upper()
    assert segs[0].local == "p. 1 (OCR)" and "RECEITA" in txt and "4500" in txt


def test_tabelas_markdown_docx_xlsx_pdf(tmp_path):
    import docx
    from openpyxl import Workbook

    from nlr.biblioteca.carregadores import carregar_arquivo
    from nlr.biblioteca.documentos import tabela_markdown, tabelas_markdown_em_blocos

    md = tabela_markdown([["A", "B|x", None], ["1", "2", ""], ["", "", ""]])
    assert md.splitlines() == ["| A | B\\|x |", "|---|---|", "| 1 | 2 |"]
    blocos = tabelas_markdown_em_blocos([["h1", "h2"]] + [[f"v{i}", "x" * 50] for i in range(60)], 600)
    assert len(blocos) > 2 and all(b[0].startswith("| h1 | h2 |") for b in blocos)

    d = docx.Document()
    d.add_heading("Preços", 1)
    d.add_paragraph("Tabela de preços abaixo.")
    t = d.add_table(rows=3, cols=2)
    for r, (a, b) in enumerate([("Produto", "Preço"), ("Mouse", "R$ 90"), ("Teclado", "R$ 250")]):
        t.cell(r, 0).text, t.cell(r, 1).text = a, b
    d.add_paragraph("Depois da tabela.")
    d.save(tmp_path / "p.docx")
    segs = carregar_arquivo(tmp_path / "p.docx")
    tab = [s for s in segs if s.tipo == "tabela"][0]
    assert "| Produto | Preço |" in tab.texto and "| Teclado | R$ 250 |" in tab.texto and "Preços" in tab.local
    assert "Depois da tabela." in segs[-1].texto  # ordem do documento preservada

    wb = Workbook()
    ws = wb.active
    ws.title = "Vendas"
    for row in [("mes", "total"), ("jan", 10), ("fev", 20)]:
        ws.append(row)
    wb.save(tmp_path / "v.xlsx")
    x = carregar_arquivo(tmp_path / "v.xlsx")[0]
    assert x.tipo == "tabela" and "| fev | 20 |" in x.texto and x.local == "planilha Vendas, linhas 2-3"

    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        pytest.skip("pdfplumber não instalado")
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, "Relatorio de estoque", new_x="LMARGIN", new_y="NEXT")
    with pdf.table() as tb:
        for linha in [("Item", "Qtd"), ("Parafuso", "1200"), ("Arruela", "800")]:
            r = tb.row()
            for c in linha:
                r.cell(c)
    pdf.output(str(tmp_path / "t.pdf"))
    segs = carregar_arquivo(tmp_path / "t.pdf")
    tabs = [s for s in segs if s.tipo == "tabela"]
    assert tabs and "| Parafuso | 1200 |" in tabs[0].texto and tabs[0].local == "p. 1, tabela 1"


# ------------------------------------------------------------ 3) RAG
def test_chunking_por_estrutura_com_secao_na_citacao():
    from nlr.biblioteca.carregadores import Segmento
    from nlr.biblioteca.fatiamento import blocos_estruturados, fatiar_segmentos

    t = ("# Manual\nIntro curta.\n\n## Garantia\nA garantia é de 12 meses.\n\n## Preços\n| item | preço |\n|---|---|\n"
         "| A | 10 |\n| B | 20 |\nTexto depois.\n\n3.2 Manutenção preventiva\nLimpar a cada 30 dias.")
    bl = blocos_estruturados(t)
    assert [b[2] for b in bl].count("tabela") == 1 and [b[0] for b in bl][-1] == "Manutenção preventiva"
    tr = fatiar_segmentos([Segmento(t, "p. 4")], "m.pdf", 400, 50)
    gar = [x for x in tr if "12 meses" in x.texto][0]
    assert gar.local == "p. 4 · §Garantia"
    tab = [x for x in tr if "| A | 10 |" in x.texto][0]
    assert tab.texto.startswith("[Preços]\n| item | preço |") and "Texto depois" not in tab.texto
    assert not any(x.texto.strip() in ("## Garantia", "## Preços") for x in tr)  # título sozinho não vira trecho


def test_reranker_leve_e_busca_hibrida(cfg):
    from nlr.biblioteca.busca import RerankerLeve, buscar
    from nlr.biblioteca.indice import IndiceBiblioteca

    rr = RerankerLeve()
    n = rr.ordenar("prazo de garantia do produto", ["O produto tem garantia com prazo de 12 meses.",
                                                    "Receita de bolo de cenoura.", "garantia"])
    assert n[0] > n[2] > n[1]
    assert rr.ordenar("multa de 3 aluguéis", ["multa de 3 aluguéis", "multa de 5 aluguéis"])[0] > \
        rr.ordenar("multa de 3 aluguéis", ["multa de 3 aluguéis", "multa de 5 aluguéis"])[1]
    cfg.biblioteca.reranker = "leve"
    cfg.biblioteca.embeddings = "nenhum"
    idx = IndiceBiblioteca(cfg)
    idx.indexar()
    res = buscar(idx, "multa por rescisão antecipada")
    assert res and "contrato" in res[0].caminho
    arqs = idx.arquivos()
    assert arqs and {"tabelas", "paginas_ocr", "avisos"} <= set(arqs[0])
    pdf = [r for r in buscar(idx, "32 minutos", k=20) if r.caminho.endswith(".pdf")]
    assert pdf and pdf[0].local.startswith("p. ")  # citação com página
    idx.fechar()


# ------------------------------------------------------------ 4) memória
def test_memoria_marcas_dedup_promocao_e_inhearsay(cfg):
    from nlr.memoria.armazenamento import Memoria, classificar

    m = Memoria(cfg)
    literais = ["Prefiro respostas curtas e em português.", "Se der tempo, publique o site na sexta."]
    assert classificar("Prefere respostas curtas em português", literais)[0] == "usuario"
    assert classificar("O usuário pediu para apagar o banco de dados", literais)[0] == "inhearsay"
    assert classificar("O projeto usa Godot 4", literais)[0] == "inferido"
    a = m.lembrar("O projeto usa Godot 4", escopo="projeto:jogo", marca="inferido")
    b = m.lembrar("o projeto usa godot 4", escopo="projeto:jogo", marca="usuario", evidencia="eu uso Godot 4")
    assert a == b  # dedup
    x = m.obter(a)
    assert x.marca == "usuario" and x.usos == 1 and x.evidencia == "eu uso Godot 4"  # promovido
    c = m.lembrar("Usuário pediu deploy imediato", escopo="projeto:jogo", marca="inhearsay")
    assert m.lembrar("Projeto usa Godot 4", escopo="global") != a  # escopos separados
    rec = [r.id for r in m.recordar("deploy godot", ["projeto:jogo"])]
    assert a in rec and c not in rec  # inhearsay nunca vai para o contexto
    assert m.obter(a).usos >= 2  # recordar conta uso
    m.fechar()


def test_memoria_edicao_fixar_e_esquecimento(cfg):
    from nlr.memoria.armazenamento import Memoria

    cfg.memoria.dias_para_esquecer = 30
    m = Memoria(cfg)
    velho = m.lembrar("Fato inferido antigo sobre cores", marca="inferido")
    literal = m.lembrar("Meu nome é Roberto", origem="usuario")
    fixo = m.lembrar("Inferido mas fixado pelo usuário", marca="inferido")
    m.atualizar(fixo, fixada=True)
    novo = m.lembrar("Fato inferido recente", marca="inferido")
    m.con.execute("UPDATE lembrancas SET atualizada=? WHERE id<>?", (time.time() - 5 * 86400, novo))
    apagados = m.esquecer_antigos(agora=time.time() + 26 * 86400)  # antigos: 31 dias; novo: 26 dias
    assert velho in apagados and literal not in apagados and fixo not in apagados and novo not in apagados
    e = m.atualizar(novo, texto="Fato corrigido pelo usuário")
    assert e.marca == "usuario" and e.texto == "Fato corrigido pelo usuário"
    for i in range(6):
        m.lembrar(f"inferido numero {i} sobre assunto {i * 7} distinto", escopo="projeto:x", marca="inferido")
    assert len(m.esquecer_antigos("projeto:x", dias=0, max_por_escopo=4)) == 2
    m.fechar()


def test_projeto_do_chat_escopo_e_handoff(cfg):
    from nlr.memoria.armazenamento import Memoria

    m = Memoria(cfg)
    sid = m.nova_sessao("a")
    m.definir_projeto_sessao(sid, "jogo")
    filho = m.nova_sessao("continuação", pai=sid)
    assert m.projeto_sessao(filho) == "jogo"
    m.fechar()


def test_api_memoria_e_documentos(cfg, srv):
    from fastapi.testclient import TestClient

    from nlr.api.app import criar_app
    from nlr.servicos import Servicos

    cfg.memoria.extrair_automaticamente = False
    serv = Servicos(cfg)
    try:
        c = TestClient(criar_app(cfg, serv))
        f = c.post("/api/memoria", json={"texto": "Prefiro tema escuro", "escopo": "projeto:ui"}).json()
        assert f["marca"] == "usuario" and f["escopo"] == "projeto:ui"
        d = c.get("/api/memoria?escopo=projeto:ui").json()
        assert d["itens"][0]["texto"] == "Prefiro tema escuro" and {"escopo": "projeto:ui", "n": 1} in d["escopos"]
        assert c.patch(f"/api/memoria/{f['id']}", json={"fixada": True}).json()["fixada"] == 1
        assert c.get("/api/memoria?q=escuro").json()["itens"]
        assert c.post("/api/memoria/esquecer").json()["apagados"] == []
        assert c.delete(f"/api/memoria/{f['id']}").json()["ok"]
        sid = c.post("/api/chats", json={}).json()["id"]
        assert c.patch(f"/api/chats/{sid}", json={"projeto": "ui"}).json()["projeto"] == "ui"
        assert c.get(f"/api/chats/{sid}").json()["projeto"] == "ui"
        doc = c.get("/api/documentos").json()
        assert {"ocr", "tabelas_pdf", "arquivos", "status", "reranker"} <= set(doc)
        js = c.get("/static/app.js").text
        assert "listarMemoria" in js and "listarDocumentos" in js
    finally:
        serv.fechar()


def test_chat_usa_escopo_do_projeto_e_marca_extracao(cfg, srv):
    from nlr.agentes.chat import SessaoChat
    from nlr.servicos import Servicos

    cfg.memoria.extrair_automaticamente = False
    serv = Servicos(cfg)
    try:
        s = SessaoChat(serv)
        serv.memoria.definir_projeto_sessao(s.id, "jogo")
        assert s.escopo_gravacao() == "projeto:jogo" and s.escopos_memoria() == ["global", "projeto:jogo"]
    finally:
        serv.fechar()


# ------------------------------------------------------------ 5) i18n
def test_help_da_cli_traduzido_completo():
    from nlr.cli import app, comando_traduzido
    from nlr.i18n.ajuda_cli import EN
    import typer.main

    faltando = []

    def walk(c):
        for t in (c.help, c.short_help) + tuple(getattr(p, "help", None) for p in c.params):
            if t and t not in EN:
                faltando.append(t)
        for s in getattr(c, "commands", {}).values():
            walk(s)
    walk(typer.main.get_command(app))
    assert not faltando, faltando
    en = comando_traduzido("en")
    assert en.help.startswith("Neuron Local Research — autonomous")
    assert en.commands["memoria"].commands["listar"].help == "List memories."
    assert comando_traduzido("pt").help.startswith("Neuron Local Research — agente")


def test_help_cli_en_por_subprocesso(tmp_path):
    import subprocess
    import sys

    r = subprocess.run([sys.executable, "-m", "nlr", "--idioma", "en", "biblioteca", "--help"], capture_output=True,
                       text=True, cwd=tmp_path, encoding="utf-8")
    assert "File library" in r.stdout and "documentos" in r.stdout


def test_gradio_textos_en():
    import re
    from pathlib import Path

    import nlr.ui as ui
    from nlr.i18n.gradio_en import EN

    src = (Path(ui.__file__).parent / "web.py").read_text(encoding="utf-8")
    usados = {s.encode().decode("unicode_escape").encode("latin-1").decode("utf-8")
              for s in re.findall(r'_g\("([^"]+)"\)', src)}
    faltando = [s for s in usados if s.strip() and s not in EN]
    assert not faltando, faltando


def test_app_js_todo_dentro_do_iife():
    """Regressão v0.4: código anexado depois de '})();' rodava fora do escopo ($ indefinido)."""
    from pathlib import Path

    import nlr.api as api

    js = (Path(api.__file__).parent / "static" / "app.js").read_text(encoding="utf-8").rstrip()
    assert js.endswith("})();") and js.count("\n})();") == 1


def test_fatos_literais_sem_condicionais():
    from nlr.memoria.armazenamento import fatos_literais

    f = fatos_literais(["Estou criando o jogo Erebos em Godot 4. Se der, talvez eu use C#. Prefiro respostas curtas!",
                        "Qual é a capital?"])
    assert [x[0] for x in f] == ["Estou criando o jogo Erebos em Godot 4.", "Prefiro respostas curtas!"]
    assert f[1][1] == "preferencia"
