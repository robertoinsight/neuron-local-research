"""Divisão em trechos (chunks): texto com cortes naturais, código por estrutura (funções/classes)."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import List

from .carregadores import Segmento

_SEPARADORES = ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ")


@dataclass
class Trecho:
    texto: str
    local: str


def normalizar(texto: str) -> str:
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    texto = re.sub(r"[ \t\f\v]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def fatiar_texto(texto: str, tamanho: int = 1200, sobreposicao: int = 200) -> List[str]:
    if tamanho < 50:
        raise ValueError("tamanho deve ser >= 50")
    sobreposicao = max(0, min(sobreposicao, tamanho // 2))
    texto = normalizar(texto)
    n = len(texto)
    if n == 0:
        return []
    if n <= tamanho:
        return [texto]
    out: List[str] = []
    ini = 0
    while ini < n:
        fim = min(ini + tamanho, n)
        if fim < n:
            lo = ini + int(tamanho * 0.5)
            for sep in _SEPARADORES:
                idx = texto.rfind(sep, lo, fim)
                if idx != -1:
                    fim = idx + len(sep)
                    break
        pedaco = texto[ini:fim].strip()
        if pedaco:
            out.append(pedaco)
        if fim >= n:
            break
        prox = max(fim - sobreposicao, ini + 1)
        if prox > 0 and not texto[prox - 1].isspace():
            sp = texto.find(" ", prox, fim)
            if sp != -1:
                prox = sp + 1
        ini = prox
    return out


# ------------------------------------------------------------------ código
_DEF_GENERICA = re.compile(
    r"^(?:export\s+)?(?:async\s+)?(?:pub\s+)?(?:public|private|protected|static|func|function|def|class|fn|impl|"
    r"interface|struct|enum|type|module|local\s+function|CREATE\s|const\s+\w+\s*=\s*(?:async\s*)?\()",
    re.IGNORECASE,
)


def _limites_python(texto: str) -> List[int]:
    """Linhas (1-based) onde começam definições de nível superior em Python."""
    try:
        arv = ast.parse(texto)
    except SyntaxError:
        return []
    inicios = []
    for no in arv.body:
        ln = no.lineno
        decs = getattr(no, "decorator_list", None) or []
        if decs:
            ln = min(ln, *[d.lineno for d in decs])
        inicios.append(ln)
    return inicios


def _limites_genericos(linhas: List[str]) -> List[int]:
    return [i + 1 for i, ln in enumerate(linhas) if ln and not ln[0].isspace() and _DEF_GENERICA.match(ln)]


def fatiar_codigo(texto: str, nome: str, tamanho: int = 1500, sobreposicao_linhas: int = 3,
                  linha_base: int = 1) -> List[Trecho]:
    """Agrupa definições (funções/classes) inteiras até ~tamanho caracteres; divide as muito grandes por linhas."""
    linhas = texto.replace("\r\n", "\n").split("\n")
    if nome.endswith(".py"):
        inicios = _limites_python(texto)
    else:
        inicios = _limites_genericos(linhas)
    if 1 not in inicios:
        inicios = [1] + inicios
    inicios = sorted(set(i for i in inicios if 1 <= i <= len(linhas)))
    blocos = []  # (ini, fim) 1-based inclusive
    for k, ini in enumerate(inicios):
        fim = (inicios[k + 1] - 1) if k + 1 < len(inicios) else len(linhas)
        blocos.append((ini, fim))

    def tam(a, b):
        return sum(len(linhas[i - 1]) + 1 for i in range(a, b + 1))

    # junta blocos pequenos vizinhos
    agrupados = []
    atual = None
    for a, b in blocos:
        if atual is None:
            atual = [a, b]
        elif tam(atual[0], b) <= tamanho:
            atual[1] = b
        else:
            agrupados.append(tuple(atual))
            atual = [a, b]
    if atual:
        agrupados.append(tuple(atual))
    # divide blocos grandes em janelas de linhas
    trechos: List[Trecho] = []
    for a, b in agrupados:
        if tam(a, b) <= tamanho * 1.3:
            janelas = [(a, b)]
        else:
            janelas = []
            i = a
            while i <= b:
                j = i
                t = 0
                while j <= b and t + len(linhas[j - 1]) + 1 <= tamanho:
                    t += len(linhas[j - 1]) + 1
                    j += 1
                j = max(j, i + 1)
                janelas.append((i, min(j - 1, b)))
                if j > b:
                    break
                i = max(j - sobreposicao_linhas, i + 1)
        for x, y in janelas:
            corpo = "\n".join(linhas[x - 1:y]).strip("\n")
            if corpo.strip():
                ox, oy = x + linha_base - 1, y + linha_base - 1
                trechos.append(Trecho(f"# arquivo: {nome} (linhas {ox}-{oy})\n{corpo}", f"linhas {ox}-{oy}"))
    return trechos


_TITULO = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_TITULO_NUM = re.compile(r"^(\d+(?:\.\d+){0,3})[.)]?\s+([A-ZÀ-Ý][^\n]{2,80})$")


def _eh_linha_tabela(ln: str) -> bool:
    t = ln.strip()
    return t.startswith("|") and t.count("|") >= 2


def blocos_estruturados(texto: str) -> List[tuple]:
    """Divide em blocos (titulo, texto, tipo) por títulos markdown/numerados; tabelas markdown ficam inteiras."""
    linhas = texto.replace("\r\n", "\n").split("\n")
    blocos: List[tuple] = []
    titulo, buf, tab = "", [], []

    def fecha_texto():
        corpo = "\n".join(buf).strip()
        so_titulo = len([x for x in buf if x.strip()]) == 1 and bool(_TITULO.match(corpo) or _TITULO_NUM.match(corpo))
        if corpo and not so_titulo:
            blocos.append((titulo, "\n".join(buf).strip(), "texto"))
        buf.clear()

    def fecha_tab():
        if tab:
            blocos.append((titulo, "\n".join(tab), "tabela"))
        tab.clear()

    for ln in linhas:
        if _eh_linha_tabela(ln):
            if not tab:
                fecha_texto()
            tab.append(ln.strip())
            continue
        fecha_tab()
        m = _TITULO.match(ln.strip()) or (_TITULO_NUM.match(ln.strip()) if len(ln) < 90 else None)
        if m:
            fecha_texto()
            titulo = m.group(2).strip()
            buf.append(ln.strip())
            continue
        buf.append(ln)
    fecha_tab()
    fecha_texto()
    return blocos


def _local(base: str, titulo: str) -> str:
    if not titulo:
        return base
    titulo = titulo[:60]
    return f"{base} · §{titulo}" if base else f"§{titulo}"


def fatiar_segmentos(segmentos: List[Segmento], nome: str, tamanho: int, sobreposicao: int) -> List[Trecho]:
    """v0.5: chunking por estrutura. Código por funções; tabelas inteiras (em blocos com cabeçalho);
    texto por seções (títulos) — cada trecho leva o título da seção no texto e na localização (citação)."""
    out: List[Trecho] = []
    for s in segmentos:
        if s.tipo == "codigo":
            out += fatiar_codigo(s.texto, nome, tamanho=max(tamanho, 600), linha_base=s.linha_inicial)
        elif s.tipo == "tabela":
            out.append(Trecho(s.texto, s.local))
        else:
            for titulo, corpo, tipo in blocos_estruturados(s.texto):
                if tipo == "tabela":
                    cab = corpo.split("\n")[:2]
                    linhas = corpo.split("\n")[2:]
                    atual: List[str] = []
                    for ln in linhas + [None]:
                        if ln is None or (atual and sum(len(x) for x in atual) + len(ln) > tamanho):
                            if atual or ln is None:
                                out.append(Trecho("\n".join(([f"[{titulo}]"] if titulo else []) + cab + atual),
                                                  _local(s.local, titulo)))
                            atual = []
                        if ln is not None:
                            atual.append(ln)
                    continue
                for p in fatiar_texto(corpo, tamanho, sobreposicao):
                    if titulo and not p.lstrip().startswith("#") and titulo not in p[:120]:
                        p = f"[{titulo}]\n{p}"
                    out.append(Trecho(p, _local(s.local, titulo)))
    return out
