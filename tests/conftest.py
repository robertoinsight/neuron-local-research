import os
import socket
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from nlr.config import Config  # noqa: E402
from tests.amostras import gerar  # noqa: E402
from tests.servidor_falso import ServidorFalso  # noqa: E402


def tem_internet() -> bool:
    try:
        socket.create_connection(("duckduckgo.com", 443), timeout=4).close()
        return True
    except OSError:
        return False


rede = pytest.mark.skipif(not tem_internet(), reason="sem acesso à internet")


@pytest.fixture(scope="session")
def servidor():
    s = ServidorFalso().iniciar()
    yield s
    s.parar()


@pytest.fixture
def srv(servidor):
    servidor.reiniciar()
    return servidor


@pytest.fixture(scope="session")
def pasta_amostras(tmp_path_factory):
    return gerar(tmp_path_factory.mktemp("biblioteca"))


@pytest.fixture
def cfg(tmp_path, srv, pasta_amostras):
    c = Config()
    c.caminho_arquivo = str(tmp_path / "config.yaml")
    c.modelo.backend = "ollama"
    c.modelo.base_url = srv.url
    c.modelo.modelo_chat = "modelo-falso"
    c.modelo.modelo_embeddings = "embed-falso"
    c.modelo.timeout = 30
    c.biblioteca.pastas = [str(pasta_amostras)]
    c.biblioteca.tamanho_trecho = 400
    c.biblioteca.sobreposicao = 60
    c.web.cache_horas = 0
    c.projetos.pesquisar_antes_de_planejar = False
    c.plugins.pastas = [str(RAIZ / "plugins")]
    return c
