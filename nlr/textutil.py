"""Utilitários de texto: tokenização simples, BM25 em memória e fusão de rankings (RRF)."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Dict, Hashable, List, Sequence

STOPWORDS = set(
    """a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sobre entre e ou mas que se
    como qual quais quem quando onde é são foi ser ter tem há ao aos à às pelo pela pelos pelas isso isto esse essa
    este esta eu me meu minha voce você sua seu suas seus the of and to in is are for on with what how who when
    where which an it this that be by from or as at""".split()
)


def sem_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


_STOP = {sem_acentos(w) for w in STOPWORDS}


def tokenizar(s: str) -> List[str]:
    s = sem_acentos((s or "").lower())
    return [t for t in re.findall(r"[a-z0-9_]+", s) if len(t) > 1 and t not in _STOP]


def bm25(consulta: str, docs: List[str], k1: float = 1.5, b: float = 0.75) -> List[float]:
    q = set(tokenizar(consulta))
    toks = [tokenizar(d) for d in docs]
    if not q or not docs:
        return [0.0] * len(docs)
    n = len(docs)
    media = (sum(len(t) for t in toks) / n) or 1.0
    df = Counter()
    for t in toks:
        for w in set(t) & q:
            df[w] += 1
    out = []
    for t in toks:
        tf = Counter(t)
        sc = 0.0
        for w in q:
            if tf[w]:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                sc += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / media))
        out.append(sc)
    return out


def rrf(rankings: Sequence[Sequence[Hashable]], k: int = 60, pesos: Sequence[float] = ()) -> Dict[Hashable, float]:
    """Reciprocal Rank Fusion: combina listas ordenadas (melhor primeiro) em uma pontuação única."""
    pont: Dict[Hashable, float] = {}
    for n, lista in enumerate(rankings):
        w = pesos[n] if n < len(pesos) else 1.0
        for pos, item in enumerate(lista):
            pont[item] = pont.get(item, 0.0) + w / (k + pos + 1)
    return pont
