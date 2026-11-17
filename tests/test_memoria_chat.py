import pytest

from nlr.agentes.chat import SessaoChat, rota_heuristica
from nlr.agentes.react import AgenteReact
from nlr.memoria.armazenamento import Memoria
from nlr.prompts import PAPEIS
from nlr.servicos import Servicos


@pytest.fixture
def serv(cfg):
    s = Servicos(cfg)
    yield s
    s.fechar()


def test_memoria_persiste_entre_sessoes(cfg, srv):
    s1 = Servicos(cfg)
    lid = s1.memoria.lembrar("SeuNome usa LM Studio com Gemma e Qwen", "fato")
    s1.memoria.lembrar("SeuNome usa LM Studio com Gemma e Qwen!", "fato")  # duplicata ignorada
    s1.memoria.lembrar("O projeto Erebos é um jogo de pixel art 480x270", "fato", "projeto:erebos")
    s1.fechar()
    s2 = Servicos(cfg)  # "outro dia": nova instância, mesmo banco
    todas = s2.memoria.listar()
    assert len(todas) == 2
    r = s2.memoria.recordar("qual programa ele usa para rodar modelos?", ["global"])
    assert r and r[0].id == lid
    assert not s2.memoria.recordar("pixel art", ["global"])  # escopo de projeto não vaza
    assert s2.memoria.recordar("jogo pixel art", ["global", "projeto:erebos"])
    assert s2.memoria.esquecer(lid) and len(s2.memoria.listar()) == 1
    s2.fechar()


def test_chat_historico_e_continuacao(cfg, srv):
    s = Servicos(cfg)
    chat = SessaoChat(s)
    r = chat.responder("Olá, tudo bem?")
    assert r.rota == "conversa" and r.texto == "Resposta simulada de conversa."
    sid = chat.id
    s.fechar()
    s2 = Servicos(cfg)
    assert s2.memoria.ultima_sessao() == sid
    chat2 = SessaoChat(s2, sid)
    assert chat2.id == sid and len(s2.memoria.historico(sid)) == 2
    chat2.responder("e agora?")
    req = srv.requisicoes[-1][1]
    assert any(m["content"] == "Olá, tudo bem?" for m in req["messages"])  # histórico enviado ao modelo
    s2.fechar()


def test_extracao_automatica_de_memoria(cfg, srv):
    s = Servicos(cfg)
    chat = SessaoChat(s)
    for msg in ["eu prefiro exemplos em Python", "ok", "certo", "valeu"]:
        chat.responder(msg, "conversa")
    assert any("prefere" in m.texto for m in s.memoria.listar("global"))
    # e a lembrança volta no prompt de conversas futuras
    chat.responder("me dê um exemplo de laço em Python", "conversa")
    sistema = srv.requisicoes[-1][1]["messages"][0]["content"]
    assert "LEMBRANÇAS" in sistema and "Python" in sistema
    s.fechar()


def test_rotas(cfg, srv):
    assert rota_heuristica("pesquise na internet sobre gemma 4") == "web"
    assert rota_heuristica("o que meus documentos dizem sobre IPCA e compare com a web") == "ambos"
    assert rota_heuristica("crie um projeto de jogo em python") == "projeto"
    assert rota_heuristica("segundo o contrato, qual a multa?") == "biblioteca"
    s = Servicos(cfg)
    s.indice.indexar()
    chat = SessaoChat(s)
    r = chat.responder("qual é a multa do contrato de aluguel?")  # roteador do modelo -> biblioteca
    assert r.rota == "biblioteca" and r.fontes and "[1]" in r.texto and "contrato.docx" in r.texto
    r = chat.responder("crie um projeto de site", "auto")
    assert r.rota == "projeto" and "nlr projeto novo" in r.texto
    s.fechar()


def test_modo_agente_no_chat(cfg, srv):
    s = Servicos(cfg)
    r = SessaoChat(s).responder("liste os arquivos", "agente")
    assert "Listei os arquivos" in r.texto
    s.fechar()


def test_react_modo_nativo(cfg, srv):
    cfg.modelo.modo_ferramentas = "nativo"
    srv.modo_nativo = True
    s = Servicos(cfg)
    ctx = s.contexto(cfg.dir_dados / "ws")
    res = AgenteReact(s.llm, s.registro, ctx, PAPEIS["geral"]).executar("TAREFA: liste os arquivos")
    assert res.concluido and res.passos[0].ferramenta == "listar_arquivos"
    assert any("tools" in q for _, q in srv.requisicoes)
    s.fechar()


def test_react_detecta_repeticao(cfg, srv):
    s = Servicos(cfg)
    ctx = s.contexto(cfg.dir_dados / "ws")
    res = AgenteReact(s.llm, s.registro, ctx, PAPEIS["geral"], max_passos=8).executar("TAREFA: repita para sempre")
    assert not res.concluido and res.motivo_parada == "repeticao" and len(res.passos) <= 4
    s.fechar()


def test_consulta_limpa_tira_instrucoes():
    from nlr.agentes.pesquisa import consulta_limpa
    assert consulta_limpa("Pesquise na minha biblioteca e na internet sobre calculadoras e desenvolva "
                          "uma calculadora em Python") == "calculadoras"
    assert consulta_limpa("pesquise sobre gemma 4") == "gemma 4"
    assert consulta_limpa("Crie um jogo da velha") == "Crie um jogo da velha"


def test_texto_completo_lista_so_fontes_citadas():
    from nlr.agentes.pesquisa import ResultadoPesquisa
    from nlr.fontes import Fonte
    fs = [Fonte(1, "biblioteca", "a.md", "a.md", "x"), Fonte(2, "web", "B", "https://b", "y")]
    r = ResultadoPesquisa(resposta="Resposta [2].\n\nFontes:\n- [2] B", fontes=fs)
    t = r.texto_completo()
    assert t.count("Fontes") == 1 and "https://b" in t and "a.md" not in t and "+1 fonte" in t
