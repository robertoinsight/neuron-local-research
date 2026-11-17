"""Utilidades de texto para respostas de modelos: remover raciocínio e extrair JSON."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def remover_raciocinio(texto: str) -> str:
    """Remove blocos <think>...</think> (e um </think> solto, se o início foi cortado)."""
    texto = _THINK_RE.sub("", texto or "")
    if "</think>" in texto and "<think>" not in texto:
        texto = texto.split("</think>", 1)[1]
    if "<think>" in texto and "</think>" not in texto:  # raciocínio truncado: descarta
        texto = texto.split("<think>", 1)[0]
    return texto.strip()


def estimar_tokens(texto: str) -> int:
    """Estimativa barata (≈3,5 caracteres por token em português/código)."""
    return int(len(texto or "") / 3.5) + 1


def _blocos_balanceados(texto: str):
    """Gera substrings que começam em { ou [ e terminam no fechamento correspondente."""
    for i, ch in enumerate(texto):
        if ch not in "{[":
            continue
        pilha = []
        em_string = False
        escape = False
        for j in range(i, len(texto)):
            c = texto[j]
            if em_string:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    em_string = False
                continue
            if c == '"':
                em_string = True
            elif c in "{[":
                pilha.append("}" if c == "{" else "]")
            elif c in "}]":
                if not pilha or pilha.pop() != c:
                    break
                if not pilha:
                    yield texto[i:j + 1]
                    break


_ESCAPES_VALIDOS = set('"\\/bfnrtu')


def _reparar(s: str) -> str:
    """Conserta erros comuns de modelos pequenos SEM mexer no conteúdo das strings (ex.: código em "conteudo"):
    escapes inválidos (\\' vira ', \\d vira \\\\d), aspas tipográficas, vírgula sobrando, True/False/None fora de strings."""
    out = []
    i, n = 0, len(s)
    dentro = False
    while i < n:
        ch = s[i]
        if dentro:
            if ch == "\\" and i + 1 < n:
                prox = s[i + 1]
                if prox in _ESCAPES_VALIDOS:
                    out.append(ch + prox)
                elif prox == "'":
                    out.append("'")
                else:
                    out.append("\\\\" + prox)
                i += 2
                continue
            if ch == '"':
                dentro = False
            out.append(ch)
            i += 1
            continue
        if ch == '"' or ch in "\u201c\u201d":
            dentro = True
            out.append('"')
            i += 1
            continue
        out.append(ch)
        i += 1
    r = "".join(out)
    # reparos fora das strings: troca só em trechos entre strings
    partes = re.split(r'("(?:[^"\\]|\\.)*")', r)
    for k in range(0, len(partes), 2):
        p = re.sub(r",\s*([}\]])", r"\1", partes[k])
        p = re.sub(r"\bTrue\b", "true", p)
        p = re.sub(r"\bFalse\b", "false", p)
        p = re.sub(r"\bNone\b", "null", p)
        partes[k] = p
    return "".join(partes)


def extrair_json(texto: str) -> Optional[Any]:
    """Tenta extrair um objeto JSON da resposta (cercas ```json, texto em volta, pequenos erros)."""
    texto = remover_raciocinio(texto)
    candidatos = [texto]
    candidatos += [m.group(1) for m in _FENCE_RE.finditer(texto)]
    for c in list(candidatos):
        candidatos += list(_blocos_balanceados(c))
    for c in candidatos:
        c = c.strip()
        if not c or c[0] not in "{[":
            continue
        for tentativa in (c, _reparar(c)):
            try:
                return json.loads(tentativa, strict=False)  # strict=False aceita quebras de linha cruas em strings
            except (json.JSONDecodeError, ValueError):
                continue
    return None
