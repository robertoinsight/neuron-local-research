"""Diagnóstico do ambiente: `nlr doctor`."""
from __future__ import annotations

import importlib
import shutil
import socket
import sys
from typing import List, Tuple

from .config import Config
from .erros import AgenteErro

Item = Tuple[str, str, str]  # (ok|aviso|erro, nome, detalhe)


def diagnosticar(cfg: Config, testar_web: bool = True, testar_mcp: bool = True) -> List[Item]:
    from .llm.cliente import ClienteLLM

    itens: List[Item] = []
    v = sys.version_info
    itens.append(("ok" if v >= (3, 10) else "erro", "Python", f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"))
    itens.append(("ok" if cfg.caminho_arquivo else "aviso", "Configuração",
                  cfg.caminho_arquivo or "nenhum config.yaml encontrado (usando padrões). Rode: nlr config criar"))
    for mod, nome, obrig in [("langgraph", "LangGraph", True), ("openai", "openai (cliente)", True),
                             ("ddgs", "ddgs (busca web)", True), ("trafilatura", "trafilatura", True),
                             ("pypdf", "pypdf", True), ("docx", "python-docx", True), ("openpyxl", "openpyxl", True),
                             ("gradio", "Gradio (interface web)", False), ("mcp", "MCP (SDK)", False),
                             ("fastembed", "fastembed (reranker opcional)", False)]:
        try:
            m = importlib.import_module(mod)
            itens.append(("ok", nome, getattr(m, "__version__", "instalado")))
        except ImportError:
            itens.append(("erro" if obrig else "aviso", nome, "não instalado"))
    llm = ClienteLLM(cfg)
    m = cfg.modelo
    from .nucleo import hardware

    hw = hardware.detectar()
    itens.append(("ok", "Hardware", hardware.resumo(hw) + f" — ~{hw.max_parametros_b()}B"))
    avisos: List[str] = []
    llm.eventos = avisos.append
    try:
        info = llm.preparar()
        modelos = info["modelos"]
        carregados = [x["id"] for x in modelos if x["carregado"]]
        itens.append(("ok", f"Servidor ({m.backend})", f"{m.url()} — {len(modelos)} modelo(s)"
                      + (f", carregado(s): {', '.join(carregados)}" if carregados else "")))
        nao_achou = [a for a in avisos if "não existe" in a or "does not exist" in a]
        itens.append(("erro" if nao_achou else "ok", "Modelo de chat",
                      nao_achou[0] if nao_achou else info["modelo_chat"]))
        for a_ in avisos:
            if a_ not in nao_achou:
                itens.append(("aviso" if "escolhi" in a_ or "picked" in a_ else "ok", "Detecção automática", a_))
        p = info["perfil"] or {}
        itens.append(("ok", "Perfil do modelo", f"{p.get('nome')} — contexto {info['contexto_tokens']} tokens "
                      f"({info['contexto_fonte']}), até {p.get('max_ferramentas')} ferramentas/passo, "
                      f"{p.get('max_passos')} passos"))
        try:
            r = llm.chat([{"role": "user", "content": "Responda só: ok"}], max_tokens=20)
            itens.append(("ok", "Teste de chat", repr(r[:40])))
        except AgenteErro as e:
            itens.append(("erro", "Teste de chat", str(e).splitlines()[0]))
        if cfg.biblioteca.embeddings != "nenhum":
            try:
                vet = llm.embeddings(["teste"])[0]
                itens.append(("ok", "Embeddings", f"{llm.principal.modelo_embeddings} (dimensão {len(vet)})"))
            except AgenteErro as e:
                itens.append(("aviso", "Embeddings", f"{str(e).splitlines()[0]} — a busca na biblioteca funciona "
                                                       "só por palavras-chave até isso ser resolvido."))
    except AgenteErro as e:
        itens.append(("erro", f"Servidor ({m.backend})", str(e)))
    if cfg.fallback.ativado:
        itens.append(("ok" if llm.reserva else "aviso", "Fallback na nuvem",
                      f"{cfg.fallback.backend} {cfg.fallback.modelo_chat}" if llm.reserva else
                      f"ativado, mas falta modelo_chat ou a chave {cfg.fallback.api_key_env} no .env"))
    pastas = cfg.pastas_biblioteca()
    if not pastas:
        itens.append(("aviso", "Biblioteca", "nenhuma pasta configurada (nlr biblioteca adicionar <pasta>)"))
    for p in pastas:
        itens.append(("ok" if p.exists() else "erro", "Pasta da biblioteca", str(p) + ("" if p.exists() else " (não existe)")))
    try:
        from .biblioteca.indice import IndiceBiblioteca

        st = IndiceBiblioteca(cfg).status()
        itens.append(("ok" if st["trechos"] else "aviso", "Índice",
                      f"{st['arquivos']} arquivo(s), {st['trechos']} trecho(s), {st['trechos_com_vetor']} com vetor"))
    except Exception as e:  # noqa: BLE001
        itens.append(("erro", "Índice", str(e)))
    try:
        teste = cfg.dir_projetos / ".teste_escrita"
        teste.write_text("ok", encoding="utf-8")
        teste.unlink()
        itens.append(("ok", "Pasta de projetos", str(cfg.dir_projetos)))
    except OSError as e:
        itens.append(("erro", "Pasta de projetos", f"sem permissão de escrita: {e}"))
    seg = cfg.seguranca
    itens.append(("ok", "Segurança", f"modo autônomo: {'LIGADO' if seg.modo_autonomo else 'desligado'}; "
                                     f"execução: {seg.execucao}; timeout: {seg.timeout_comando}s"))
    if seg.execucao == "docker" and not shutil.which("docker"):
        itens.append(("erro", "Docker", "seguranca.execucao=docker, mas o Docker não está no PATH"))
    if testar_web:
        try:
            socket.create_connection(("duckduckgo.com", 443), timeout=5).close()
            itens.append(("ok", "Internet", "duckduckgo.com acessível"))
        except OSError as e:
            itens.append(("aviso", "Internet", f"sem acesso ({e}); a busca na web não vai funcionar"))
    if testar_mcp and cfg.mcp.servidores:
        from .ferramentas.mcp_cliente import GerenciadorMCP

        g = GerenciadorMCP(cfg)
        g.conectar()
        for nome, con in g.conexoes.items():
            itens.append(("ok", f"MCP {nome}", f"{len(con.ferramentas)} ferramenta(s)"))
        for nome, erro in g.erros.items():
            itens.append(("erro", f"MCP {nome}", erro))
        g.fechar()
    return itens
