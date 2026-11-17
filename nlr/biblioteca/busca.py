"""Busca híbrida na biblioteca: BM25 (FTS5) + vetores, fundidos por RRF e, opcionalmente, reranqueados."""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from ..config import Config
from ..textutil import rrf
from .indice import IndiceBiblioteca, Resultado

log = logging.getLogger(__name__)


class Reranker:
    """Reranqueador cross-encoder local (CPU, ONNX) via fastembed. Opcional: pip install fastembed."""

    def __init__(self, modelo: str):
        from fastembed.rerank.cross_encoder import TextCrossEncoder  # import tardio

        self.m = TextCrossEncoder(model_name=modelo)

    def ordenar(self, consulta: str, textos: List[str]) -> List[float]:
        return [float(x) for x in self.m.rerank(consulta, textos)]


class RerankerLeve:
    """Reranqueador sem dependências (v0.5): cobertura dos termos da pergunta (sem acento, por radical),
    proximidade (pares de termos vizinhos), números exatos e título/seção. Rápido em CPU fraca."""

    def ordenar(self, consulta: str, textos: List[str]) -> List[float]:
        from ..textutil import tokenizar

        def rad(t):
            return t[:5]

        q = [rad(t) for t in tokenizar(consulta) if len(t) > 2]
        nums = set(re.findall(r"\d+(?:[.,]\d+)?", consulta))
        pares = set(zip(q, q[1:]))
        notas = []
        for tx in textos:
            toks = [rad(t) for t in tokenizar(tx)]
            ts = set(toks)
            cob = (sum(1 for t in set(q) if t in ts) / len(set(q))) if q else 0.0
            prox = (sum(1 for p in zip(toks, toks[1:]) if p in pares) / len(pares)) if pares else 0.0
            num = (sum(1 for n in nums if n in tx) / len(nums)) if nums else 0.0
            cab = tx[:160]
            tit = 0.15 if q and any(t in [rad(x) for x in tokenizar(cab)] for t in q) else 0.0
            notas.append(cob + 0.5 * min(prox, 1.0) + 0.5 * num + tit)
        return notas


_RERANKER_CACHE = {}


def obter_reranker(cfg: Config):
    if cfg.biblioteca.reranker == "leve":
        return RerankerLeve()
    if cfg.biblioteca.reranker != "fastembed":
        return None
    nome = cfg.biblioteca.modelo_reranker
    if nome not in _RERANKER_CACHE:
        try:
            _RERANKER_CACHE[nome] = Reranker(nome)
        except Exception as e:  # noqa: BLE001
            log.warning("Reranker indisponível (%s); seguindo sem ele. Instale: pip install fastembed", e)
            _RERANKER_CACHE[nome] = RerankerLeve()
    return _RERANKER_CACHE[nome]


def buscar(indice: IndiceBiblioteca, consulta: str, k: Optional[int] = None, consultas_extras: Optional[List[str]] = None,
           max_por_arquivo: int = 3) -> List[Resultado]:
    """Busca híbrida. consultas_extras: variações da pergunta (ex.: geradas pelo modelo) que entram na fusão."""
    cfg = indice.cfg
    k = k or cfg.biblioteca.k
    consultas = [consulta] + [c for c in (consultas_extras or []) if c and c != consulta]
    listas, pesos = [], []
    for q in consultas:
        listas.append([i for i, _ in indice.buscar_bm25(q, 50)])
        pesos.append(1.0)
        vet = indice.buscar_vetor(q, 50)
        if vet:
            listas.append([i for i, _ in vet])
            pesos.append(cfg.biblioteca.peso_vetor)
    fus = rrf(listas, pesos=pesos)
    if not fus:
        return []
    ordem = sorted(fus, key=lambda i: -fus[i])[: max(k * 4, 20)]
    linhas = indice.trechos_por_id(ordem)
    candidatos = [(i, fus[i]) for i in ordem if i in linhas]
    rr = obter_reranker(cfg)
    if rr and candidatos:
        try:
            notas = rr.ordenar(consulta, [linhas[i][3] for i, _ in candidatos])
            if isinstance(rr, RerankerLeve):  # combina com a fusão (não descarta o sinal semântico)
                mx = max(f for _, f in candidatos) or 1.0
                notas = [0.6 * n + 0.8 * (f / mx) for n, (_, f) in zip(notas, candidatos)]
            candidatos = sorted(zip([i for i, _ in candidatos], notas), key=lambda x: -x[1])
        except Exception as e:  # noqa: BLE001
            log.warning("Falha no reranker: %s", e)
    por_arquivo: dict = {}
    out: List[Resultado] = []
    for i, nota in candidatos:
        _, caminho, local, texto, raiz = linhas[i]
        if por_arquivo.get(caminho, 0) >= max_por_arquivo:
            continue
        por_arquivo[caminho] = por_arquivo.get(caminho, 0) + 1
        out.append(Resultado(caminho=caminho, local=local or "", texto=texto, pontuacao=float(nota), raiz=raiz or ""))
        if len(out) >= k:
            break
    return out
