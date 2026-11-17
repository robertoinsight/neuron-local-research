import sys
from pathlib import Path

import pytest

from nlr.config import ServidorMCP
from nlr.servicos import Servicos

SCRIPT = str(Path(__file__).parent / "mcp_servidor_teste.py")


def _cfg_mcp(cfg, permissao):
    cfg.mcp.timeout = 30
    cfg.mcp.servidores = {"teste": ServidorMCP(command=sys.executable, args=[SCRIPT], permissao=permissao)}
    return cfg


def test_mcp_livre(cfg, srv, tmp_path):
    s = Servicos(_cfg_mcp(cfg, "livre"), usar_mcp=True)
    nomes = s.conectar_mcp()
    assert "mcp_teste__somar" in nomes and "mcp_teste__ecoar" in nomes
    ctx = s.contexto(tmp_path)
    assert s.registro.executar("mcp_teste__somar", {"a": 2, "b": 40}, ctx).strip() == "42"
    assert "eco: olá" in s.registro.executar("mcp_teste__ecoar", {"texto": "olá"}, ctx)
    s.fechar()


@pytest.mark.parametrize("resposta,esperado", [(None, "PERMISSÃO NEGADA"), (False, "PERMISSÃO NEGADA"), (True, "5")])
def test_mcp_confirmar(cfg, srv, tmp_path, resposta, esperado):
    conf = None if resposta is None else (lambda t, d: resposta)
    s = Servicos(_cfg_mcp(cfg, "confirmar"), confirmar=conf, usar_mcp=True)
    s.conectar_mcp()
    out = s.registro.executar("mcp_teste__somar", {"a": 2, "b": 3}, s.contexto(tmp_path))
    assert esperado in out
    s.fechar()


def test_mcp_servidor_quebrado_nao_derruba(cfg, srv, tmp_path):
    cfg.mcp.timeout = 10
    cfg.mcp.servidores = {"ruim": ServidorMCP(command="comando-que-nao-existe-xyz")}
    s = Servicos(cfg, usar_mcp=True)
    assert s.conectar_mcp() == []
    assert "ruim" in s.mcp.erros
    s.fechar()
