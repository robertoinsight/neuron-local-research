"""Roteador de ferramentas: mostra ao modelo só as ferramentas relevantes para o pedido.

Modelos pequenos erram muito mais quando veem 20+ ferramentas. O roteador dá uma nota a cada ferramenta
(palavras do pedido x nome/descrição/grupos + gatilhos por grupo) e devolve as N melhores, sempre incluindo
as essenciais. Não usa o modelo (custo zero, determinístico).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Sequence

GATILHOS = {
    "arquivos": "arquivo arquivos pasta ler escrever salvar criar editar file folder read write save edit txt md csv",
    "codigo": "codigo código programa script python rodar executar testar teste comando terminal bug erro run test code",
    "pesquisa": "pesquisar pesquise pesquisa web internet site fonte fontes buscar busque procurar noticia biblioteca "
                "documento documentos pdf search source library",
    "memoria": "lembrar lembre memoria memória preferencia esqueça remember memory",
    "util": "calcular data hora converter calculate date time",
    "mcp": "",
    "pixel": "pixel sprite sprites spritesheet paleta palette aseprite ase tileset gif animacao animação redimensionar "
             "upscale fundo transparente pico-8 db32 endesga gameboy",
    "abnt": "abnt referencia referência referencias citacao citação nbr 6023 10520 14724 doi isbn tcc monografia "
            "trabalho academico acadêmico capa sumario sumário bibliografia",
}
ESSENCIAIS = ("ler_arquivo", "escrever_arquivo", "buscar_biblioteca", "pesquisar_web")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _palavras(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9_]{3,}", _norm(s))}


def pontuar(ferr, palavras_pedido: set) -> float:
    texto = f"{ferr.nome.replace('_', ' ')} {ferr.descricao}"
    alvo = _palavras(texto)
    nota = 2.0 * len(palavras_pedido & _palavras(ferr.nome.replace("_", " "))) + len(palavras_pedido & alvo)
    for g in ferr.grupos:
        nota += 0.7 * len(palavras_pedido & _palavras(GATILHOS.get(g, "")))
    return nota


def selecionar(ferramentas: Sequence, pedido: str, limite: int, essenciais: Iterable[str] = ESSENCIAIS) -> List:
    if limite <= 0 or len(ferramentas) <= limite:
        return list(ferramentas)
    p = _palavras(pedido)
    notas = sorted(((pontuar(f, p), i, f) for i, f in enumerate(ferramentas)), key=lambda x: (-x[0], x[1]))
    escolhidas = [f for nota, _, f in notas if nota > 0][:limite]
    ess = set(essenciais)
    for f in ferramentas:
        if len(escolhidas) >= limite:
            break
        if f.nome in ess and f not in escolhidas:
            escolhidas.append(f)
    for _, _, f in notas:  # completa até o limite
        if len(escolhidas) >= limite:
            break
        if f not in escolhidas:
            escolhidas.append(f)
    return escolhidas
