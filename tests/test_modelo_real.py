"""Teste opcional com um servidor de modelos DE VERDADE.

Rode com:  AGENTE_TESTE_REAL=1 AGENTE_MODELO=qwen3.5:2b python -m pytest -q tests/test_modelo_real.py
(precisa do Ollama no ar com o modelo de chat e o qwen3-embedding:0.6b)."""
import os

import pytest

from nlr.agentes.chat import SessaoChat
from nlr.config import Config
from nlr.servicos import Servicos

pytestmark = [pytest.mark.modelo_real,
              pytest.mark.skipif(os.environ.get("AGENTE_TESTE_REAL") != "1", reason="defina AGENTE_TESTE_REAL=1")]


def test_pergunta_na_biblioteca_com_modelo_real(tmp_path, pasta_amostras):
    c = Config()
    c.caminho_arquivo = str(tmp_path / "config.yaml")
    c.modelo.backend = os.environ.get("AGENTE_BACKEND", "ollama")
    c.modelo.modelo_chat = os.environ.get("AGENTE_MODELO", "qwen3.5:2b")
    c.modelo.modelo_embeddings = os.environ.get("AGENTE_EMBED", "qwen3-embedding:0.6b")
    c.biblioteca.pastas = [str(pasta_amostras)]
    s = Servicos(c)
    s.indice.indexar()
    r = SessaoChat(s).responder("Qual é a multa por rescisão antecipada do contrato?", "biblioteca")
    assert "três" in r.texto.lower() or "3" in r.texto
    assert any("contrato.docx" in f.titulo for f in r.fontes)
    s.fechar()
