"""Pesquisa na internet DE VERDADE (ddgs + trafilatura). Pula se não houver internet; tolera limite de requisições."""
import pytest

from nlr.agentes.pesquisa import pesquisar
from nlr.erros import AgenteErro
from nlr.servicos import Servicos
from nlr.web.busca import PesquisaWeb
from tests.conftest import rede


def _ou_pular(fn):
    try:
        res = fn()
        if not res:
            pytest.skip("buscador não retornou resultados (bloqueio ou limite neste ambiente)")
        return res
    except AgenteErro as e:
        if "limit" in str(e).lower() or "falhou" in str(e).lower():
            pytest.skip(f"buscador limitou as requisições: {e}")
        raise


@rede
def test_busca_e_leitura_real(cfg):
    w = PesquisaWeb(cfg)
    res = _ou_pular(lambda: w.buscar("Python programming language official site"))
    assert res and all(r.url.startswith("http") for r in res)
    pg = w.ler_pagina("https://www.python.org/about/")
    assert pg.baixada and "Python" in pg.texto
    fontes = _ou_pular(lambda: w.pesquisar("what is the python programming language"))
    assert fontes and fontes[0].n == 1 and fontes[0].tipo == "web"


@rede
def test_pesquisa_cruzada_biblioteca_e_web(cfg, srv):
    s = Servicos(cfg)
    s.indice.indexar()
    ctx = s.contexto(cfg.dir_dados / "ws")
    r = _ou_pular(lambda: pesquisar(ctx, "drone bateria de litio autonomia", usar_biblioteca=True, usar_web=True))
    tipos = {f.tipo for f in r.fontes}
    if "web" not in tipos:
        pytest.skip(f"a web não trouxe resultados agora: {r.avisos}")
    assert "biblioteca" in tipos
    assert "Biblioteca × Web" in r.resposta  # seção de cruzamento pedida ao modelo
    assert "**Fontes**" in r.texto_completo()
    s.fechar()


def test_cache_web(cfg, tmp_path):
    cfg.web.cache_horas = 1
    w = PesquisaWeb(cfg)
    w.cache.put("busca:ddgs:br-pt:teste", [{"titulo": "T", "url": "https://exemplo.com", "resumo": "R"}])
    assert w.buscar("teste")[0].url == "https://exemplo.com"
    with pytest.raises(AgenteErro):
        w.ler_pagina("file:///etc/passwd")
