"""Fase 5: análise de imagens com modelo de visão e pesquisa a partir de imagens."""
from PIL import Image

from nlr.fontes import Fonte
from nlr.servicos import Servicos


def _ctx(cfg, tmp_path):
    s = Servicos(cfg)
    s.registro  # garante ferramentas embutidas carregadas
    return s, s.contexto(tmp_path)


def test_analisar_imagem_grande_usa_quadrantes(cfg, srv, tmp_path):
    Image.new("RGB", (2000, 1200), (200, 30, 30)).save(tmp_path / "foto.jpg")
    s, ctx = _ctx(cfg, tmp_path)
    r = s.registro.executar("analisar_imagem", {"caminho": "foto.jpg"}, ctx)
    assert "2000x1200" in r and "5 vista(s)" in r  # visão geral + 4 quadrantes
    req = srv.requisicoes[-1][1]
    partes = req["messages"][-1]["content"]
    assert all(p["image_url"]["url"].startswith("data:image/jpeg;base64,") for p in partes if p["type"] == "image_url")


def test_pixel_art_e_modelo_visao(cfg, srv, tmp_path):
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    img.putpixel((3, 3), (255, 0, 0, 255))
    img.save(tmp_path / "sprite.png")
    cfg.modelo.modelo_visao = "modelo-falso"
    s, ctx = _ctx(cfg, tmp_path)
    r = s.registro.executar("analisar_imagem", {"caminho": "sprite.png", "modo": "pixel"}, ctx)
    assert "pixel art" in r and "1 vista(s)" in r
    assert srv.requisicoes[-1][1]["model"] == "modelo-falso"


def test_imagem_fora_da_pasta_e_formato(cfg, srv, tmp_path):
    (tmp_path / "a.txt").write_text("x")
    s, ctx = _ctx(cfg, tmp_path)
    assert "não suportado" in s.registro.executar("analisar_imagem", {"caminho": "a.txt"}, ctx)
    assert "não encontrada" in s.registro.executar("analisar_imagem", {"caminho": "nada.png"}, ctx)


def test_pesquisar_por_imagem(cfg, srv, tmp_path, monkeypatch):
    Image.new("RGB", (300, 200), (240, 140, 20)).save(tmp_path / "gato.jpg")
    s, ctx = _ctx(cfg, tmp_path)
    vistas = []

    def falso(consulta, status=None):
        vistas.append(consulta)
        return [Fonte(n=0, tipo="web", titulo="Gatos laranja", referencia="https://exemplo.org/gato", texto="Gatos...")]

    monkeypatch.setattr(ctx.web, "pesquisar", falso)
    r = s.registro.executar("pesquisar_por_imagem", {"caminho": "gato.jpg", "foco": "que raça"}, ctx)
    assert vistas == ["gato laranja teclado"]
    assert "um gato laranja sobre um teclado" in r and "https://exemplo.org/gato" in r and "[1]" in r
