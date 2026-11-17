"""Testes da fase 4 (v0.6): Kit Pixel Art e Kit ABNT (sem rede, sem Aseprite real)."""
import base64
import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from nlr.i18n import definir_idioma  # noqa: E402
from nlr.kits import abnt as A  # noqa: E402
from nlr.kits import paletas as P  # noqa: E402
from nlr.kits import pixel as X  # noqa: E402


@pytest.fixture(autouse=True)
def _pt():
    definir_idioma("pt")
    yield
    definir_idioma("pt")


def sprite(w=128, h=128, cor=(200, 30, 40, 255), fundo=(0, 255, 0, 255)):
    im = Image.new("RGBA", (w, h), fundo)
    for x in range(w // 4, 3 * w // 4):
        for y in range(h // 4, 3 * h // 4):
            im.putpixel((x, y), cor)
    return im


# ------------------------------------------------------------------ pixel
def test_redimensionar_nearest_sem_cores_novas():
    im = sprite()
    p = X.redimensionar(im, largura=32)
    assert p.size == (32, 32)
    assert set(p.getdata()) <= set(im.getdata())
    assert X.redimensionar(im, fator=0.5).size == (64, 64)
    assert X.upscale(p, 4).size == (128, 128)


def test_paletas_conhecidas_e_aplicar_lab():
    for n in ("pico-8", "db32", "endesga-32", "gameboy"):
        assert P.obter(n)
    assert len(P.obter("pico-8")) == 16 and len(P.obter("db32")) == 32
    out = X.aplicar_paleta(sprite(), "pico-8").convert("RGB")
    cores = set(out.getdata())
    assert cores <= set(P.obter("pico-8"))
    assert (255, 0, 77) in cores  # vermelho -> vermelho PICO-8 (não marrom)
    assert set(X.aplicar_paleta(sprite(), "db32", dither=True).convert("RGB").getdata()) <= set(P.obter("db32"))


def test_paleta_arquivos_gpl_hex(tmp_path):
    cores = P.obter("gameboy")
    for ext in (".gpl", ".hex", ".pal"):
        f = P.salvar_paleta(cores, tmp_path / f"gb{ext}") or tmp_path / f"gb{ext}"
        assert P.obter(str(f)) == cores
    assert P.obter("#000000,#ffffff") == [(0, 0, 0), (255, 255, 255)]
    assert X.extrair_paleta(sprite())[:2]


def test_reduzir_e_remover_fundo():
    im = sprite()
    assert len(set(X.reduzir_paleta(im, 2).convert("RGBA").getdata())) <= 2
    s = X.remover_fundo(im)
    assert s.getpixel((0, 0))[3] == 0 and s.getpixel((64, 64))[3] == 255


def test_spritesheet_montar_fatiar_gif(tmp_path):
    qs = [sprite(16, 16, cor=(i * 60, 0, 0, 255)) for i in range(4)]
    folha, meta = X.montar(qs, colunas=2)
    assert folha.size == (32, 32) and len(meta["frames"]) == 4
    assert len(X.fatiar(folha, 16, 16)) == 4
    g = X.gif(qs, tmp_path / "a.gif", fator=2)
    with Image.open(g) as im:
        assert im.n_frames == 4 and im.size == (32, 32)
    assert X.preview(qs[0]).size[0] >= 128


def test_ase_roundtrip_e_fallback_sem_aseprite(tmp_path):
    qs = [sprite(8, 8), sprite(8, 8, cor=(0, 0, 255, 255))]
    f = X.escrever_ase_rgba(qs, tmp_path / "s.aseprite", duracao_ms=120) or tmp_path / "s.aseprite"
    d = X.ler_ase(f)
    assert len(d["quadros"]) == 2 and d["duracoes"][0] == 120
    assert list(d["quadros"][1].getdata()) == list(qs[1].getdata())
    ase = X.Aseprite(executavel="")
    assert not ase.disponivel
    pngs = ase.exportar_png(f, tmp_path / "out" / "q.png", escala=2)
    assert len(pngs) == 2 and Image.open(pngs[0]).size == (16, 16)
    png, js = ase.exportar_sheet(f, tmp_path / "out" / "sheet.png")
    assert Image.open(png).size == (16, 8) and len(json.loads(js.read_text())["frames"]) == 2
    with pytest.raises(RuntimeError):
        ase.rodar_script(tmp_path / "x.lua")


@pytest.mark.skipif(sys.platform == "win32", reason="script shell falso")
def test_aseprite_falso_detectado_e_args(tmp_path, monkeypatch):
    log = tmp_path / "args.txt"
    exe = tmp_path / "aseprite"
    exe.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\necho "Aseprite 1.3-falso"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("ASEPRITE", str(exe))
    assert X.detectar_aseprite("") == str(exe)
    assert X.detectar_aseprite(str(tmp_path / "naoexiste")) == str(exe)
    a = X.Aseprite()
    assert "falso" in a.versao()
    a.exportar_sheet(tmp_path / "s.aseprite", tmp_path / "sh.png", tipo="packed")
    a.rodar_script(tmp_path / "p.lua", {"paleta": "db32.gpl"}, arquivo=tmp_path / "s.aseprite")
    linhas = log.read_text().splitlines()
    assert linhas[0].startswith("--batch --version")
    assert "--sheet" in linhas[1] and "--sheet-type packed" in linhas[1] and "--format json-hash" in linhas[1]
    assert "--script-param paleta=db32.gpl" in linhas[2] and linhas[2].endswith("p.lua")
    assert len(X.salvar_scripts_lua(tmp_path / "lua")) == 3


def test_caminhos_aseprite_windows_inclui_steam(monkeypatch):
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
    txt = " ".join(str(c) for c in X.caminhos_aseprite())
    assert "Aseprite.exe" in txt and "steamapps" in txt.lower()


# ------------------------------------------------------------------ registro / kits
def test_kits_desligados_nao_aparecem_para_o_agente(cfg):
    from nlr.servicos import Servicos

    s = Servicos(cfg)
    nomes = lambda: {f.nome for f in s.registro.listar()}  # noqa: E731
    assert not any(n.startswith(("pixel_", "abnt_")) for n in nomes())
    cfg.kits.pixel.ativo = True
    cfg.kits.abnt.ativo = True
    s.aplicar_kits()
    assert {"pixel_imagem", "pixel_spritesheet", "pixel_aseprite", "abnt_referencia", "abnt_documento"} <= nomes()
    cfg.kits.pixel.ativo = False
    s.aplicar_kits()
    assert "pixel_imagem" not in nomes() and "abnt_referencia" in nomes()


# ------------------------------------------------------------------ ABNT
def livro():
    return A.Referencia(tipo="livro", autores=[A.Autor.de_nome("George Orwell")], titulo="1984", local="São Paulo",
                        editora="Companhia das Letras", ano="2009")


def test_autor_nomes():
    assert A.Autor.de_nome("Maria Clara de Souza Filho").referencia() == "SOUZA FILHO, Maria Clara de"
    assert A.Autor.de_nome("Silva, João").referencia() == "SILVA, João"


def test_formatar_livro_artigo_site():
    assert A.formatar_referencia(livro()) == "ORWELL, George. **1984**. São Paulo: Companhia das Letras, 2009."
    art = A.Referencia(tipo="artigo", autores=[A.Autor("LeCun", "Yann"), A.Autor("Bengio", "Yoshua"), A.Autor("Hinton", "Geoffrey")],
                       titulo="Deep learning", periodico="Nature", volume="521", numero="7553", paginas="436-444",
                       ano="2015", doi="10.1038/nature14539")
    s = A.formatar_referencia(art)
    assert s.startswith("LECUN, Yann; BENGIO, Yoshua; HINTON, Geoffrey. Deep learning. **Nature**")
    assert "v. 521" in s and "p. 436-444" in s and "DOI: 10.1038/nature14539" in s
    assert A.citacao(art) == "(LeCun; Bengio; Hinton, 2015)"
    assert A.citacao(art, norma="2002") == "(LECUN; BENGIO; HINTON, 2015)"
    art.autores.append(A.Autor("Fulano", "X"))
    assert A.formatar_referencia(art).startswith("LECUN, Yann et al.")
    assert A.citacao(art, pagina="437") == "(LeCun et al., 2015, p. 437)"
    site = A.Referencia(tipo="site", titulo="Pixel art", url="https://ex.org/p", acesso="2026-11-02")
    s = A.formatar_referencia(site)
    assert s.startswith("PIXEL art") and "Disponível em: https://ex.org/p" in s and "Acesso em: 2 nov. 2026" in s
    assert site.avisos  # sem data -> [20--] com aviso


def test_ordenacao_e_desambiguacao():
    a = A.Referencia(tipo="livro", autores=[A.Autor("Silva", "Ana")], titulo="B", ano="2020")
    b = A.Referencia(tipo="livro", autores=[A.Autor("Silva", "Ana")], titulo="A", ano="2020")
    lista = A.lista_referencias([livro(), a, b])
    assert lista[0].startswith("ORWELL") and lista[1].startswith("SILVA")
    A.desambiguar_anos([a, b])
    assert {A.citacao(a), A.citacao(b)} == {"(Silva, 2020a)", "(Silva, 2020b)"}


def test_isbn_doi():
    assert A.isbn_valido("9788535914849") and not A.isbn_valido("9788535914840")
    assert A.normalizar_doi("https://doi.org/10.1038/NATURE14539").lower() == "10.1038/nature14539"


def test_crossref_e_html_offline():
    r = A.de_crossref({"type": "journal-article", "title": ["Um título"], "author": [{"family": "Souza", "given": "Ana"}],
                       "container-title": ["Revista X"], "volume": "3", "issue": "2", "page": "10-20",
                       "issued": {"date-parts": [[2021, 5]]}, "DOI": "10.1/abc"})
    assert r.tipo == "artigo" and r.ano == "2021" and r.autores[0].sobrenome == "Souza"
    html = """<html><head><title>Guia – Site X</title><meta name="citation_title" content="Guia de sprites">
      <meta name="citation_author" content="Pedro Alves"><meta name="citation_publication_date" content="2019/03/01">
      <meta property="og:site_name" content="Site X"></head></html>"""
    h = A.metadados_html(html, "https://x.org/g")
    assert h.titulo == "Guia de sprites" and h.ano == "2019" and h.autores[0].sobrenome == "Alves"


def test_gerar_docx_nbr14724(tmp_path):
    docx = pytest.importorskip("docx")
    t = A.Trabalho(titulo="Pixel art em jogos", autor="Roberto Teste", instituicao="Universidade X", local="São Paulo",
                   ano="2026", natureza="Trabalho de Conclusão de Curso")
    corpo = "# Introdução\nTexto (Orwell, 2009).\n## Objetivos\nMais.\n> " + "citação longa " * 20 + "\n# Conclusão\nFim."
    refs = [A.Referencia(tipo="livro", autores=[A.Autor("Zeta", "Z")], titulo="Z", ano="2000"), livro()]
    f = A.gerar_docx(t, corpo, refs, tmp_path / "t.docx")
    d = docx.Document(str(f))
    s = d.sections[-1]
    cm = lambda v: round(v.cm, 1)  # noqa: E731
    assert (cm(s.left_margin), cm(s.top_margin), cm(s.right_margin), cm(s.bottom_margin)) == (3.0, 3.0, 2.0, 2.0)
    textos = [p.text for p in d.paragraphs]
    assert "REFERÊNCIAS" in textos and any(x.startswith("1 INTRODUÇÃO") for x in textos)
    assert any(x.startswith("1.1") for x in textos)
    i = len(textos) - 1 - textos[::-1].index("REFERÊNCIAS")
    refs_txt = [x for x in textos[i + 1:] if x.strip()]
    assert refs_txt[0].startswith("ORWELL") and refs_txt[1].startswith("ZETA")
    xml = d.element.xml
    assert "TOC" in xml
    assert "PAGE" in d.sections[-1].header._element.xml and "PAGE" not in d.sections[0].header._element.xml
    estilo = d.styles["Normal"]
    assert estilo.font.name == "Times New Roman" and estilo.font.size.pt == 12
    assert estilo.paragraph_format.line_spacing == 1.5


def test_relatorio_profundo_abnt_offline(tmp_path):
    pytest.importorskip("docx")
    from nlr.agentes.profunda import RelatorioProfundo
    from nlr.fontes import Fonte

    fontes = [Fonte(1, "web", "Guia de pixel art", "https://ex.org/guia", "t"),
              Fonte(2, "web", "Outro guia", "https://outro.net/b", "t")]
    md = "# Pixel art\n\n## Resumo\nA paleta importa [1]. Sprites pequenos [1, 2].\n\n## Fontes\n[1] ...\n"
    rel = RelatorioProfundo("pixel art", md, fontes, [], [], [], 0)
    assert "(Ex.org" not in A.converter_citacoes(md, {1: A.de_fonte(fontes[0], False)})
    destino, refs = A.relatorio_abnt(rel, tmp_path / "r-abnt.docx", buscar_online=False)
    assert destino.exists() and len(refs) == 2
    import docx

    t = "\n".join(p.text for p in docx.Document(str(destino)).paragraphs)
    assert "[1]" not in t and "FONTES" not in t and "REFERÊNCIAS" in t and "Disponível em: https://ex.org/guia" in t


# ------------------------------------------------------------------ API
@pytest.fixture
def cliente(cfg, tmp_path):
    from fastapi.testclient import TestClient

    from nlr.api.app import criar_app
    from nlr.servicos import Servicos

    cfg.memoria.extrair_automaticamente = False
    cfg.caminho_arquivo = None
    os.chdir(tmp_path)
    return TestClient(criar_app(cfg, Servicos(cfg)))


def _b64(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def test_api_kits_pixel(cliente):
    k = cliente.get("/api/kits").json()
    assert not k["pixel"]["ativo"] and "pico-8" in k["pixel"]["paletas"]
    assert cliente.put("/api/kits", json={"pixel": True, "salvar": False}).json()["pixel"]["ativo"]
    r = cliente.post("/api/pixel", json={"acao": "redimensionar", "imagens_b64": [_b64(sprite())], "largura": 32}).json()
    assert r["tamanho"].startswith("32")
    arq = cliente.get(r["url"])
    assert arq.status_code == 200 and Image.open(io.BytesIO(arq.content)).size == (32, 32)
    r = cliente.post("/api/pixel", json={"acao": "extrair_paleta", "imagens_b64": [_b64(sprite())]}).json()
    assert "#00ff00" in [c.lower() for c in r["paleta"]]
    r = cliente.post("/api/pixel", json={"acao": "montar", "imagens_b64": [_b64(sprite(16, 16))] * 3}).json()
    assert r.get("json")
    assert cliente.get("/api/kits/arquivo/pixel/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)


def test_api_abnt(cliente, monkeypatch):
    pytest.importorskip("docx")
    monkeypatch.setattr(A, "identificar", lambda s: livro())
    r = cliente.post("/api/abnt/referencias", json={"identificadores": ["9788535914849"]}).json()
    assert r["itens"][0]["citacao"] == "(Orwell, 2009)"
    d = cliente.post("/api/abnt/documento", json={"titulo": "Meu Trabalho", "texto": "# Intro\nOi.",
                                                  "referencias_prontas": [r["itens"][0]["dados"]]}).json()
    assert d["arquivo"] == "meu-trabalho-abnt.docx" and d["referencias"] == 1
    assert cliente.get(d["url"]).status_code == 200


def test_ui_tem_aba_kits_e_i18n():
    from nlr.i18n.ui import EN, PT

    base = Path(__file__).parent.parent / "nlr" / "api" / "static"
    js, html = (base / "app.js").read_text(encoding="utf-8"), (base / "index.html").read_text(encoding="utf-8")
    assert 'data-view="kits"' in html and 'id="view-kits"' in html and "prof-abnt" in html
    assert "function abrirKits" in js and js.rstrip().endswith("})();")
    assert js.index("function abrirKits") < js.rindex("})();")
    import re

    for k in set(re.findall(r'\bt\("([a-z_0-9]+)"\)', js)) | {"px_" + a for a in ("gif", "montar", "fatiar")}:
        assert k in PT and k in EN, k


def test_cli_pixel_abnt(tmp_path):
    from typer.testing import CliRunner

    from nlr.cli import app

    f = tmp_path / "s.png"
    sprite().save(f)
    r = CliRunner().invoke(app, ["pixel", "redimensionar", str(f), "--largura", "32"])
    assert r.exit_code == 0, r.output
    assert any(Image.open(p).size == (32, 32) for p in tmp_path.glob("*.png") if p != f)
    r = CliRunner().invoke(app, ["pixel", "paletas"])
    assert r.exit_code == 0 and "pico-8" in r.output
    r = CliRunner().invoke(app, ["abnt", "--help"])
    assert r.exit_code == 0 and "ref" in r.output
