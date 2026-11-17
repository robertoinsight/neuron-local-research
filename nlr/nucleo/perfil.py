"""Perfis por tamanho de modelo: o NLR extrai o máximo de cada modelo ajustando ferramentas, passos e orçamento.

pequeno (< 5B):  poucas ferramentas por passo, prompts curtos, mais tentativas de JSON, pesquisa mais enxuta.
medio  (5-15B):  equilíbrio (padrão para GPUs de 8-12 GB).
grande (> 15B):  todas as ferramentas relevantes, mais passos, mais páginas lidas na pesquisa.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Perfil:
    nome: str
    max_ferramentas: int
    max_passos: int
    tentativas_json: int
    fracao_historico: float  # parte do contexto reservada ao histórico
    obs_recente: int  # caracteres da observação mais recente mantidos no prompt
    obs_antiga: int
    paginas_web: int
    rodadas_pesquisa: int
    max_tokens_resposta: int

    def dict(self) -> dict:
        return asdict(self)


PERFIS = {
    "pequeno": Perfil("pequeno", max_ferramentas=5, max_passos=8, tentativas_json=4, fracao_historico=0.5,
                      obs_recente=2500, obs_antiga=300, paginas_web=3, rodadas_pesquisa=1, max_tokens_resposta=1024),
    "medio": Perfil("medio", max_ferramentas=9, max_passos=12, tentativas_json=3, fracao_historico=0.6,
                    obs_recente=6000, obs_antiga=600, paginas_web=5, rodadas_pesquisa=2, max_tokens_resposta=2048),
    "grande": Perfil("grande", max_ferramentas=20, max_passos=20, tentativas_json=2, fracao_historico=0.65,
                     obs_recente=12000, obs_antiga=1200, paginas_web=8, rodadas_pesquisa=3, max_tokens_resposta=4096),
}


def classificar(parametros_b: float, contexto: int = 0) -> str:
    if parametros_b <= 0:
        nome = "medio"
    elif parametros_b < 5:
        nome = "pequeno"
    elif parametros_b <= 15:
        nome = "medio"
    else:
        nome = "grande"
    # contexto curto limita o que cabe no prompt, mesmo em modelo grande
    if contexto and contexto < 6000 and nome != "pequeno":
        nome = "pequeno" if contexto < 4500 else "medio"
    return nome


def obter(nome: str = "auto", parametros_b: float = 0.0, contexto: int = 0) -> Perfil:
    if nome in PERFIS:
        return PERFIS[nome]
    return PERFIS[classificar(parametros_b, contexto)]


def max_tokens_para(perfil: Perfil, contexto: int) -> int:
    """Resposta nunca maior que ~1/4 do contexto (sobra espaço para prompt e histórico)."""
    return max(256, min(perfil.max_tokens_resposta, contexto // 4 if contexto else perfil.max_tokens_resposta))
