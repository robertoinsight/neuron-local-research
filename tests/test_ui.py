import socket

import pytest
import requests

pytest.importorskip("gradio", reason="interface Gradio é opcional (extra ui)")

from nlr.ui.web import construir  # noqa: E402


def _porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_ui_sobe_e_responde(cfg, srv):
    demo = construir(cfg)
    porta = _porta_livre()
    demo.launch(server_name="127.0.0.1", server_port=porta, prevent_thread_lock=True, inbrowser=False)
    try:
        r = requests.get(f"http://127.0.0.1:{porta}/", timeout=20)
        assert r.status_code == 200 and "gradio" in r.text.lower()
        cfg_r = requests.get(f"http://127.0.0.1:{porta}/config", timeout=20)
        assert cfg_r.status_code == 200 and "Conversa" in cfg_r.text and "Projetos" in cfg_r.text
    finally:
        demo.close()
        demo._agente_servicos.fechar()


def test_ui_conversa_streaming(cfg, srv):
    demo = construir(cfg)
    fn = next(d.fn for d in demo.fns.values() if getattr(d.fn, "__name__", "") == "conversar")
    saidas = list(fn("Olá!", [], "conversa", ""))
    hist, caixa, sid = saidas[-1]
    assert hist[0] == {"role": "user", "content": "Olá!"}
    assert hist[-1]["content"] == "Resposta simulada de conversa." and sid and caixa == ""
    # mesma sessão é reaproveitada
    hist2, _, sid2 = list(fn("de novo", hist, "conversa", sid))[-1]
    assert sid2 == sid and len(hist2) == 4
    demo._agente_servicos.fechar()
