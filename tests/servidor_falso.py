"""Servidor FALSO compatível com a API OpenAI — SÓ PARA TESTES (não é um modelo de verdade).

Implementa /v1/models, /v1/chat/completions (com/sem stream, response_format, tools) e /v1/embeddings.
O "cérebro" roteirizado reconhece cada tipo de prompt do agente (roteador, planejador, laço de ferramentas,
revisor...) e devolve respostas plausíveis e determinísticas, o que permite testar o fluxo completo:
criar um projeto real (arquivos + testes executados), interromper, retomar etc.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = 256

CALC_OK = '''"""Calculadora simples."""


def somar(a, b):
    return a + b


def subtrair(a, b):
    return a - b


def multiplicar(a, b):
    return a * b


def dividir(a, b):
    if b == 0:
        raise ValueError("divisão por zero")
    return a / b
'''

CALC_BUG = CALC_OK.replace("return a - b", "return a + b  # bug proposital")

TESTE_CALC = '''from calc import dividir, multiplicar, somar, subtrair
import pytest


def test_operacoes():
    assert somar(2, 3) == 5
    assert subtrair(5, 3) == 2
    assert multiplicar(4, 3) == 12
    assert dividir(9, 3) == 3


def test_divisao_por_zero():
    with pytest.raises(ValueError):
        dividir(1, 0)
'''


def _achatar(c):
    """Conteúdo multimodal (lista de partes) vira texto; imagens viram o marcador [imagem]."""
    if isinstance(c, list):
        return "\n".join(p.get("text", "") if p.get("type") == "text" else "[imagem]" for p in c)
    return c


def _norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def hash_embed(text: str):
    v = [0.0] * DIM
    for w in re.findall(r"[a-z0-9]+", _norm(text)):
        if len(w) < 3 or w in ("search", "query", "document", "instruct", "dada", "pergunta", "encontre", "trechos"):
            continue
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class Cerebro:
    """Respostas roteirizadas. Atributos ajustáveis pelos testes."""

    def __init__(self):
        self.bug_na_primeira = False   # 1ª versão de calc.py com bug (testa reprovação + correção)
        self.json_invalido_vezes = 0   # quantas respostas JSON inválidas antes da correta
        self.falhar_quando = None      # texto que, se aparecer no prompt, gera HTTP 500 (simula queda)
        self.escritas_calc = 0
        self.chamadas = 0

    # ---------------------------------------------------------------- utilidades
    @staticmethod
    def _observacoes(msgs):
        return [m["content"] for m in msgs if m["role"] == "user" and m["content"].startswith("OBSERVAÇÃO")]

    def _acao(self, ferramenta, argumentos, pensamento="ok"):
        return json.dumps({"pensamento": pensamento, "ferramenta": ferramenta, "argumentos": argumentos},
                          ensure_ascii=False)

    # ---------------------------------------------------------------- laço de ferramentas
    def _react(self, msgs):
        tarefa = msgs[1]["content"]
        obs = self._observacoes(msgs)
        n = len(obs)
        t = _norm(tarefa)
        m = re.search(r"SUA TAREFA AGORA \(nº (\d+)", tarefa)
        if "tarefa: liste os arquivos" in t:  # usado no modo /agente do chat
            return [self._acao("listar_arquivos", {"pasta": "."}),
                    self._acao("finalizar", {"resposta": "Listei os arquivos da área de trabalho."})][min(n, 1)]
        if "tarefa: repita" in t:
            return self._acao("listar_arquivos", {"pasta": "."})
        if not m:
            return self._acao("finalizar", {"resposta": "Tarefa genérica concluída."})
        if "tipo pesquisa" in t:
            passos = [self._acao("buscar_biblioteca", {"consulta": "calculadora operações"}),
                      self._acao("escrever_arquivo", {"caminho": "NOTAS.md",
                                                      "conteudo": "# Notas\n\nRequisitos: somar, subtrair, multiplicar, dividir [1].\n"}),
                      self._acao("finalizar", {"resposta": "Notas salvas em NOTAS.md [1]."})]
            return passos[min(n, 2)]
        if "tipo codigo" in t:
            if n == 0:
                self.escritas_calc += 1
                conteudo = CALC_BUG if (self.bug_na_primeira and self.escritas_calc == 1) else CALC_OK
                return self._acao("escrever_arquivo", {"caminho": "calc.py", "conteudo": conteudo})
            if n == 1 and "test_calc.py" not in tarefa.split("ARQUIVOS NA PASTA DO PROJETO:")[-1]:
                return self._acao("escrever_arquivo", {"caminho": "test_calc.py", "conteudo": TESTE_CALC})
            return self._acao("finalizar", {"resposta": "calc.py implementado."})
        if "tipo teste" in t:
            passos = [self._acao("escrever_arquivo", {"caminho": "test_calc.py", "conteudo": TESTE_CALC}),
                      self._acao("executar_comando", {"comando": "python -m pytest -q"}),
                      self._acao("finalizar", {"resposta": "Testes escritos e executados."})]
            return passos[min(n, 2)]
        if "tipo docs" in t:
            passos = [self._acao("ler_arquivo", {"caminho": "calc.py"}),
                      self._acao("escrever_arquivo", {"caminho": "README.md", "conteudo":
                                 "# Calculadora\n\nFunções: somar, subtrair, multiplicar, dividir.\n\n"
                                 "## Testes\n\n    python -m pytest -q\n"}),
                      self._acao("finalizar", {"resposta": "README.md escrito."})]
            return passos[min(n, 2)]
        return self._acao("finalizar", {"resposta": "ok"})

    # ---------------------------------------------------------------- despacho
    def responder(self, req):
        msgs = [dict(m, content=_achatar(m.get("content"))) for m in req["messages"]]
        if any(isinstance(m.get("content"), str) and "[imagem]" in m["content"] for m in msgs):
            self.imagens_recebidas = getattr(self, "imagens_recebidas", 0) + 1
            if "Responda SÓ com JSON" in msgs[-1]["content"] and "pessoa" in msgs[-1]["content"] and "PESSOAS-TESTE" in msgs[-1]["content"]:
                return json.dumps({"descricao": "duas pessoas numa praia", "texto_visivel": "", "tem_pessoas": True,
                                   "consultas": ["praia"]}, ensure_ascii=False)
            if "Responda SÓ com JSON" in msgs[-1]["content"]:
                return json.dumps({"descricao": "um gato laranja sobre um teclado", "texto_visivel": "ENTER",
                                   "consultas": ["gato laranja teclado"]}, ensure_ascii=False)
            return "Visão geral: imagem de teste com " + str(msgs[-1]["content"].count("[imagem]")) + " vista(s)."
        sistema = msgs[0]["content"] if msgs and msgs[0]["role"] == "system" else ""
        ultimo = msgs[-1]["content"]
        if ultimo.startswith("Sua resposta não foi aceita"):  # nova tentativa: responde à pergunta original
            ultimo = next(m["content"] for m in msgs if m["role"] == "user")
        tudo = "\n".join(m["content"] for m in msgs if isinstance(m.get("content"), str))
        self.chamadas += 1
        if self.falhar_quando and self.falhar_quando in tudo:
            return {"erro": 500}
        if "schema" in sistema.lower() and self.json_invalido_vezes > 0:
            self.json_invalido_vezes -= 1
            return "claro! aqui vai: {isso não é json"
        if "Você é um classificador" in sistema:
            q = _norm(ultimo)
            rota = "biblioteca" if "contrato" in q else "web" if "presidente" in q else "conversa"
            return json.dumps({"rota": rota})
        if "Gere de 1 a 3 consultas" in sistema:
            # imita um modelo: pega as palavras "de conteúdo" da pergunta, sem as instruções
            from nlr.agentes.pesquisa import consulta_limpa
            palavras = re.findall(r"\w+", consulta_limpa(ultimo))[:4]
            return json.dumps({"consultas": [" ".join(palavras) + " python"]}, ensure_ascii=False)
        if "Extraia do texto abaixo" in sistema:
            if "prefiro" in _norm(ultimo) or "prefere" in _norm(ultimo):
                return json.dumps({"lembrancas": [{"texto": "O usuário prefere respostas com exemplos em Python",
                                                   "tipo": "preferencia"}]}, ensure_ascii=False)
            if "projeto" in _norm(ultimo):
                return json.dumps({"lembrancas": [{"texto": "Projetos de calculadora usam pytest para testes",
                                                   "tipo": "licao"}]}, ensure_ascii=False)
            return json.dumps({"lembrancas": []})
        if "Resuma a conversa" in sistema:
            return "- resumo simulado do progresso"
        if "Você é o PLANEJADOR" in sistema:
            return json.dumps({"resumo": "Calculadora em Python com testes e documentação.", "tarefas": [
                {"titulo": "Levantar requisitos", "descricao": "Pesquisar requisitos e salvar NOTAS.md", "tipo": "pesquisa",
                 "criterios_aceite": ["arquivo NOTAS.md existe"], "depende_de": []},
                {"titulo": "Implementar calc.py", "descricao": "Criar calc.py com as 4 operações e test_calc.py",
                 "tipo": "codigo", "criterios_aceite": ["arquivo calc.py existe", "pytest passa"], "depende_de": [1]},
                {"titulo": "Documentar", "descricao": "Criar README.md", "tipo": "docs",
                 "criterios_aceite": ["arquivo README.md existe"], "depende_de": [2]},
            ]}, ensure_ascii=False)
        if "Você é o REVISOR" in sistema:
            return json.dumps({"aprovado": True, "problemas": [], "sugestoes": ""})
        if "relatório final" in sistema:
            return "## Resumo\nCalculadora criada com testes (pytest) e README."
        if "FERRAMENTAS:" in sistema:
            return self._react(msgs)
        if "FONTES:" in ultimo:
            nums = re.findall(r"^\[(\d+)\]", ultimo, flags=re.M)
            cites = "".join(f"[{x}]" for x in nums[:2])
            extra = "\n\n## Biblioteca × Web\nAs duas concordam [1]." if "Biblioteca × Web" in sistema else ""
            return f"<think>analisando fontes</think>Resposta simulada baseada nas fontes {cites}.{extra}"
        if "Responda só: ok" in ultimo:
            return "ok"
        return "<think>pensando</think>Resposta simulada de conversa."


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # v0.7: simula o LM Studio (/api/v0/models com type vlm e /api/v1/models com capabilities.vision)
        if self.path.rstrip("/").endswith("/api/v0/models"):
            if self.server.lmstudio_v0 is None:
                return self._json(404, {"error": {"message": "not found"}})
            return self._json(200, {"object": "list", "data": self.server.lmstudio_v0})
        if self.path.rstrip("/").endswith("/api/v1/models"):
            if self.server.lmstudio_v1 is None:
                return self._json(404, {"error": {"message": "not found"}})
            return self._json(200, {"models": self.server.lmstudio_v1})
        if self.path.rstrip("/").endswith("/models"):
            return self._json(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in self.server.modelos]})
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        srv = self.server
        srv.requisicoes.append((self.path, req))
        if self.path.endswith("/embeddings"):
            if srv.falhar_embeddings:
                return self._json(404, {"error": {"message": "model not found"}})
            inp = req["input"] if isinstance(req["input"], list) else [req["input"]]
            return self._json(200, {"object": "list", "model": req.get("model"),
                                    "data": [{"object": "embedding", "index": i, "embedding": hash_embed(t)} for i, t in enumerate(inp)],
                                    "usage": {"prompt_tokens": 1, "total_tokens": 1}})
        if not self.path.endswith("/chat/completions"):
            return self._json(404, {"error": {"message": "not found"}})
        rf = req.get("response_format") or {}
        if srv.recusar_json_schema and rf.get("type") == "json_schema":
            return self._json(400, {"error": {"message": "response_format json_schema not supported"}})
        if req.get("model") not in srv.modelos:
            return self._json(404, {"error": {"message": f"model '{req.get('model')}' not found"}})
        with srv.trava:
            resp = srv.cerebro.responder(req)
        if isinstance(resp, dict) and "erro" in resp:
            return self._json(resp["erro"], {"error": {"message": "falha simulada do servidor"}})
        mensagem = {"role": "assistant", "content": resp}
        if req.get("tools") and srv.modo_nativo:
            dado = None
            try:
                dado = json.loads(re.sub(r"<think>.*?</think>", "", resp, flags=re.S))
            except (json.JSONDecodeError, TypeError):
                pass
            if isinstance(dado, dict) and "ferramenta" in dado:
                mensagem = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": f"call_{len(srv.requisicoes)}", "type": "function",
                    "function": {"name": dado["ferramenta"], "arguments": json.dumps(dado["argumentos"], ensure_ascii=False)}}]}
        fim = "stop"
        if srv.cortar_vezes > 0 and isinstance(resp, str) and resp.startswith("{") and not req.get("tools"):
            srv.cortar_vezes -= 1
            srv.max_tokens_vistos.append(req.get("max_tokens"))
            mensagem = {"role": "assistant", "content": resp[: max(5, len(resp) // 2)]}
            fim = "length"
        if not req.get("stream"):
            return self._json(200, {"id": "x", "object": "chat.completion", "created": 0, "model": req.get("model"),
                                    "choices": [{"index": 0, "finish_reason": fim, "message": mensagem}],
                                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def enviar(obj):
            payload = ("data: " + (obj if isinstance(obj, str) else json.dumps(obj)) + "\n\n").encode()
            self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")

        for i in range(0, len(resp), 4):  # pedaços pequenos: corta as tags <think> no meio
            enviar({"id": "x", "object": "chat.completion.chunk", "created": 0, "model": req.get("model"),
                    "choices": [{"index": 0, "delta": {"content": resp[i:i + 4]}, "finish_reason": None}]})
        enviar({"id": "x", "object": "chat.completion.chunk", "created": 0, "model": req.get("model"),
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        enviar("[DONE]")
        self.wfile.write(b"0\r\n\r\n")


class ServidorFalso:
    def __init__(self, modelos=("modelo-falso", "embed-falso"), porta=0):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", porta), _Handler)
        self.httpd.modelos = list(modelos)
        self.httpd.requisicoes = []
        self.httpd.falhar_embeddings = False
        self.httpd.recusar_json_schema = False
        self.httpd.modo_nativo = False
        self.httpd.cortar_vezes = 0
        self.httpd.max_tokens_vistos = []
        self.httpd.lmstudio_v0 = None
        self.httpd.lmstudio_v1 = None
        self.httpd.cerebro = Cerebro()
        self.httpd.trava = threading.Lock()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __getattr__(self, nome):
        return getattr(self.httpd, nome)

    def __setattr__(self, nome, valor):
        if nome in ("httpd", "thread"):
            object.__setattr__(self, nome, valor)
        else:
            setattr(self.httpd, nome, valor)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def reiniciar(self):
        self.httpd.cerebro = Cerebro()
        self.httpd.requisicoes.clear()
        self.httpd.falhar_embeddings = False
        self.httpd.recusar_json_schema = False
        self.httpd.modo_nativo = False
        self.httpd.cortar_vezes = 0
        self.httpd.max_tokens_vistos = []
        self.httpd.lmstudio_v0 = None
        self.httpd.lmstudio_v1 = None

    def iniciar(self):
        self.thread.start()
        return self

    def parar(self):
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    import sys

    s = ServidorFalso(porta=int(sys.argv[1]) if len(sys.argv) > 1 else 11434).iniciar()
    print("Servidor falso em", s.url)
    s.thread.join()
