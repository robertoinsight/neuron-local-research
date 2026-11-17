"""Idiomas do Neuron Local Research: pt (padrão) e en.

Uso:  from nlr.i18n import t, definir_idioma
      definir_idioma("en"); print(t("modelo.auto_escolhido", modelo="qwen"))
Idioma: config.yaml (idioma: pt|en), variável NLR_IDIOMA ou opção --idioma da CLI.
Para traduzir para outro idioma, copie o dicionário EN, traduza e registre em TEXTOS.
"""
from __future__ import annotations

import os
from typing import Dict

from .textos import EN, PT

TEXTOS: Dict[str, Dict[str, str]] = {"pt": PT, "en": EN}
IDIOMAS = tuple(TEXTOS)
_atual = {"idioma": "pt"}


def normalizar(idioma: str) -> str:
    i = (idioma or "pt").strip().lower().replace("_", "-")
    if i.startswith("en"):
        return "en"
    return "pt"


def definir_idioma(idioma: str) -> str:
    _atual["idioma"] = normalizar(idioma)
    return _atual["idioma"]


def idioma_atual() -> str:
    return _atual["idioma"]


def iniciar(cfg=None) -> str:
    """Escolhe o idioma: NLR_IDIOMA > config.idioma > pt."""
    return definir_idioma(os.environ.get("NLR_IDIOMA") or (getattr(cfg, "idioma", None) if cfg else None) or "pt")


def t(chave: str, idioma: str = "", **kw) -> str:
    tab = TEXTOS.get(normalizar(idioma) if idioma else _atual["idioma"], PT)
    modelo = tab.get(chave) or PT.get(chave) or chave
    try:
        return modelo.format(**kw)
    except (KeyError, IndexError):
        return modelo


def instrucao_idioma(idioma: str = "") -> str:
    """Frase adicionada ao prompt de sistema para o modelo responder no idioma do usuário."""
    return t("prompt.idioma", idioma)
