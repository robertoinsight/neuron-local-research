from typing import List

import pytest
from pydantic import BaseModel

from nlr.config import Config
from nlr.erros import BackendIndisponivel, SaidaInvalida
from nlr.llm.cliente import ClienteLLM, FiltroRaciocinio
from nlr.llm.texto import extrair_json, remover_raciocinio


class Rota(BaseModel):
    rota: str


class Lista(BaseModel):
    itens: List[int]


def test_extrair_json_variantes():
    assert extrair_json('{"a": 1}') == {"a": 1}
    assert extrair_json('Claro!\n```json\n{"a": [1, 2,]}\n```') == {"a": [1, 2]}
    assert extrair_json('<think>{"x":0}</think>texto {"b": true} fim') == {"b": True}
    assert extrair_json("{'a': 1}") is None or isinstance(extrair_json("{'a': 1}"), dict)
    assert extrair_json("nada aqui") is None
    assert extrair_json('{"t": "chave } dentro"}') == {"t": "chave } dentro"}


def test_remover_raciocinio_e_filtro():
    assert remover_raciocinio("<think>a</think>Oi") == "Oi"
    assert remover_raciocinio("resto</think>Oi") == "Oi"
    f = FiltroRaciocinio()
    saida = "".join(f.feed(p) for p in ["<thi", "nk>seg", "redo</th", "ink>Olá ", "mundo"]) + f.flush()
    assert saida == "Olá mundo"


def test_chat_e_streaming(cfg, srv):
    llm = ClienteLLM(cfg)
    assert llm.chat([{"role": "user", "content": "oi"}]) == "Resposta simulada de conversa."
    pedacos = []
    txt = llm.chat([{"role": "user", "content": "oi"}], ao_receber=pedacos.append)
    assert txt == "Resposta simulada de conversa." and len(pedacos) > 1
    assert "think" not in "".join(pedacos)


def test_chat_json_valida_e_tenta_de_novo(cfg, srv):
    srv.cerebro.json_invalido_vezes = 1
    llm = ClienteLLM(cfg)
    r = llm.chat_json([{"role": "system", "content": "Você é um classificador."},
                       {"role": "user", "content": "Mensagem do usuário: meu contrato"}], Rota)
    assert r.rota == "biblioteca"
    reqs = [q for p, q in srv.requisicoes if p.endswith("/chat/completions")]
    assert len(reqs) == 2  # 1 inválida + 1 válida
    assert reqs[0]["response_format"]["type"] == "json_schema"


def test_chat_json_desiste_com_mensagem(cfg, srv):
    srv.cerebro.json_invalido_vezes = 10
    with pytest.raises(SaidaInvalida) as e:
        ClienteLLM(cfg).chat_json([{"role": "user", "content": "x"}], Lista, tentativas=2)
    assert "JSON válido" in str(e.value)


def test_rebaixa_quando_servidor_recusa_json_schema(cfg, srv):
    srv.recusar_json_schema = True
    llm = ClienteLLM(cfg)
    r = llm.chat_json([{"role": "system", "content": "Você é um classificador."},
                       {"role": "user", "content": "Mensagem do usuário: quem é o presidente"}], Rota)
    assert r.rota == "web"
    assert llm._modo_estruturado == "json_object"


@pytest.mark.parametrize("backend,porta", [("ollama", 11434), ("lmstudio", 1234), ("llamacpp", 8080)])
def test_selecao_de_backend_e_erro_amigavel(backend, porta):
    c = Config()
    c.modelo.backend = backend
    assert c.modelo.url().endswith(f":{porta}/v1")
    c.modelo.base_url = "http://127.0.0.1:9/v1"  # porta fechada
    c.modelo.timeout = 3
    with pytest.raises(BackendIndisponivel) as e:
        ClienteLLM(c).chat([{"role": "user", "content": "oi"}])
    msg = str(e.value)
    assert "Não consegui conectar" in msg and "nlr doctor" in msg


def test_fallback_para_nuvem(cfg, srv, monkeypatch):
    monkeypatch.setenv("CHAVE_TESTE", "abc")
    cfg.modelo.base_url = "http://127.0.0.1:9/v1"
    cfg.fallback.ativado = True
    cfg.fallback.base_url = srv.url
    cfg.fallback.modelo_chat = "modelo-falso"
    cfg.fallback.api_key_env = "CHAVE_TESTE"
    avisos = []
    llm = ClienteLLM(cfg, eventos=avisos.append)
    assert llm.chat([{"role": "user", "content": "oi"}]) == "Resposta simulada de conversa."
    assert llm.usando_reserva and avisos


def test_modelo_auto_lmstudio(cfg, srv):
    cfg.modelo.backend = "lmstudio"
    cfg.modelo.modelo_chat = "auto"
    cfg.modelo.modelo_embeddings = "auto"
    llm = ClienteLLM(cfg)
    assert llm.chat([{"role": "user", "content": "oi"}])
    assert llm.principal.modelo_chat == "modelo-falso"
    assert len(llm.embeddings(["a"])[0]) == 256


def test_modelo_inexistente(cfg, srv):
    cfg.modelo.modelo_chat = "nao-existe:7b"
    with pytest.raises(Exception) as e:
        ClienteLLM(cfg).chat([{"role": "user", "content": "oi"}])
    assert "ollama pull nao-existe:7b" in str(e.value)


def test_reparo_json_nao_estraga_codigo():
    # erros reais vistos com qwen3.5:2b: \' dentro de strings e quebras de linha cruas
    r = extrair_json('{"ferramenta": "escrever_arquivo", "argumentos": {"caminho": "a.py", '
                     '"conteudo": "import csv\nopen(\\\'vendas.csv\\\')\nx = None\n",}}')
    assert r["argumentos"]["conteudo"] == "import csv\nopen('vendas.csv')\nx = None\n"
    assert extrair_json(r'{"c": "re.match(r\d+)"}') == {"c": r"re.match(r\d+)"}


def test_resposta_cortada_pede_algo_menor_e_aumenta_limite(cfg, srv):
    srv.cortar_vezes = 1
    cfg.modelo.max_tokens = 1000
    llm = ClienteLLM(cfg)
    r = llm.chat_json([{"role": "system", "content": "Você é um classificador."},
                       {"role": "user", "content": "Mensagem do usuário: meu contrato"}], Rota)
    assert r.rota == "biblioteca"
    reqs = [q for p, q in srv.requisicoes if p.endswith("/chat/completions")]
    assert reqs[0]["max_tokens"] == 1000 and reqs[1]["max_tokens"] == 2000
    assert "CORTADA" in reqs[1]["messages"][-1]["content"]
