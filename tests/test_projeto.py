"""Fluxo completo do agente de projetos com o servidor falso: cria arquivos de verdade e roda o pytest de verdade."""
import json
from pathlib import Path

import pytest

from nlr.agentes.projeto import ExecutorProjeto
from nlr.agentes.projeto_store import ProjetoStore
from nlr.erros import AgenteErro
from nlr.servicos import Servicos


@pytest.fixture
def serv(cfg):
    cfg.seguranca.modo_autonomo = True  # comandos da lista (python/pytest) rodam sem perguntar
    s = Servicos(cfg)
    s.indice.indexar()
    yield s
    s.fechar()


def _tarefas(info):
    return json.loads((Path(info.pasta) / ".agente" / "tarefas.json").read_text(encoding="utf-8"))["tarefas"]


def test_projeto_completo_cria_testa_e_documenta(serv, srv):
    eventos = []
    ex = ExecutorProjeto(serv, eventos=lambda t, m: eventos.append((t, m)))
    info = ex.novo("Crie uma calculadora em Python com testes e README")
    ex.fechar()
    pasta = Path(info.pasta)
    assert info.status == "concluido", info.erro
    for arq in ("NOTAS.md", "calc.py", "test_calc.py", "README.md", "PLANO.md", "DIARIO.md", "RELATORIO.md"):
        assert (pasta / arq).exists(), arq
    tarefas = _tarefas(info)
    assert [t["status"] for t in tarefas] == ["concluida"] * 3
    diario = (pasta / "DIARIO.md").read_text(encoding="utf-8")
    assert "APROVADA" in diario
    # o revisor rodou o pytest de verdade e ele passou
    assert any(t == "comando" and "pytest" in m for t, m in eventos)
    assert "[x] **2. Implementar calc.py**" in (pasta / "PLANO.md").read_text(encoding="utf-8")
    # memória de longo prazo: fato global sobre o projeto + lição no escopo do projeto
    globais = [m.texto for m in serv.memoria.listar("global")]
    assert any(info.id in t for t in globais)
    assert serv.memoria.listar(f"projeto:{info.id}")
    # a pesquisa na biblioteca usada pela tarefa de pesquisa gerou fonte citável
    assert "[1]" in (pasta / "NOTAS.md").read_text(encoding="utf-8")


def test_revisao_reprova_e_executor_corrige(serv, srv):
    srv.cerebro.bug_na_primeira = True
    ex = ExecutorProjeto(serv)
    info = ex.novo("Calculadora com bug na primeira versao")
    ex.fechar()
    t2 = _tarefas(info)[1]
    assert t2["status"] == "concluida" and t2["tentativas"] == 2
    diario = (Path(info.pasta) / "DIARIO.md").read_text(encoding="utf-8")
    assert "REPROVADA" in diario and "pytest FALHOU" in diario
    assert "bug proposital" not in (Path(info.pasta) / "calc.py").read_text(encoding="utf-8")


def test_retomar_apos_interrupcao(serv, srv):
    srv.cerebro.falhar_quando = "SUA TAREFA AGORA (nº 3"  # o "servidor cai" na 3ª tarefa
    ex = ExecutorProjeto(serv)
    with pytest.raises(AgenteErro):
        ex.novo("Calculadora interrompida")
    ex.fechar()
    store = ProjetoStore(serv.cfg)
    info = store.listar()[0]
    assert info.status == "interrompido"
    st = [t["status"] for t in _tarefas(info)]
    assert st[:2] == ["concluida", "concluida"] and st[2] in ("pendente", "em_andamento")
    escritas_antes = srv.cerebro.escritas_calc
    srv.cerebro.falhar_quando = None
    ex2 = ExecutorProjeto(serv)  # novo processo/objeto: estado vem do checkpoint SQLite
    info2 = ex2.retomar(info.id)
    ex2.fechar()
    assert info2.status == "concluido"
    assert srv.cerebro.escritas_calc == escritas_antes  # não refez a tarefa 2
    assert (Path(info2.pasta) / "README.md").exists()
    assert "Retomando" in (Path(info2.pasta) / "DIARIO.md").read_text(encoding="utf-8")


def test_retomar_sem_checkpoint_reconstroi_de_tarefas_json(serv, srv):
    srv.cerebro.falhar_quando = "SUA TAREFA AGORA (nº 3"
    ex = ExecutorProjeto(serv)
    with pytest.raises(AgenteErro):
        ex.novo("Calculadora sem checkpoint")
    ex.fechar()
    serv.cfg.db_checkpoints.unlink()  # simula perda do banco de checkpoints
    srv.cerebro.falhar_quando = None
    info = ProjetoStore(serv.cfg).listar()[0]
    ex2 = ExecutorProjeto(serv)
    info2 = ex2.retomar(info.id)
    ex2.fechar()
    assert info2.status == "concluido"
    assert [t["status"] for t in _tarefas(info2)] == ["concluida"] * 3


def test_planejador_invalido_usa_plano_padrao(serv, srv):
    srv.cerebro.json_invalido_vezes = 3  # o planejador erra todas as tentativas
    ex = ExecutorProjeto(serv)
    info = ex.novo("Projeto com planejador confuso")
    ex.fechar()
    tarefas = _tarefas(info)
    assert tarefas[0]["titulo"] == "Entender e detalhar o objetivo" and len(tarefas) == 4
    assert "plano padrão" in (Path(info.pasta) / "DIARIO.md").read_text(encoding="utf-8")


def test_sem_modo_autonomo_comandos_sao_negados_sem_confirmacao(cfg, srv):
    cfg.seguranca.modo_autonomo = False
    s = Servicos(cfg, confirmar=None)
    ex = ExecutorProjeto(s)
    info = ex.novo("Calculadora sem permissão para comandos")
    ex.fechar()
    diario = (Path(info.pasta) / "DIARIO.md").read_text(encoding="utf-8")
    assert "Não rodei os testes" in diario
    assert (Path(info.pasta) / "calc.py").exists()  # escrever arquivos no projeto é permitido
    s.fechar()


def test_continuar_projeto(serv, srv):
    ex = ExecutorProjeto(serv)
    info = ex.novo("Calculadora base")
    info2 = ex.continuar(info.id, "adicione potência")
    ex.fechar()
    assert info2.status == "concluido" and "adicione potência" in info2.objetivo
    assert "::" in info2.thread
