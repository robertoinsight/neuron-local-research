"""Anti-loop: percebe quando o agente repete ações, alterna entre as mesmas duas ou acumula erros."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import List, Optional

from ..i18n import t


def _assinatura(ferramenta: str, args: dict) -> str:
    return hashlib.md5(f"{ferramenta}|{json.dumps(args, sort_keys=True, ensure_ascii=False)}".encode()).hexdigest()


@dataclass
class Veredito:
    acao: str  # ok | avisar | parar
    mensagem: str = ""


@dataclass
class GuardaLoop:
    max_repeticoes: int = 3
    max_erros: int = 4
    _hist: List[str] = field(default_factory=list)
    _obs: List[str] = field(default_factory=list)
    _erros: int = 0
    avisos: int = 0

    def antes(self, ferramenta: str, args: dict) -> Veredito:
        """Chamado antes de executar a ação."""
        a = _assinatura(ferramenta, args)
        self._hist.append(a)
        rep = 1
        for x in reversed(self._hist[:-1]):
            if x != a:
                break
            rep += 1
        if rep >= self.max_repeticoes:
            return Veredito("parar", t("guarda.parou"))
        if rep >= 2:
            self.avisos += 1
            return Veredito("avisar", t("guarda.repeticao", n=rep))
        h = self._hist
        if len(h) >= 6 and h[-1] == h[-3] == h[-5] and h[-2] == h[-4] == h[-6] and h[-1] != h[-2]:
            self.avisos += 1
            if self.avisos > 3:
                return Veredito("parar", t("guarda.parou"))
            return Veredito("avisar", t("guarda.oscilacao"))
        return Veredito("ok")

    def depois(self, observacao: str) -> Optional[str]:
        """Chamado com o resultado; devolve um aviso extra para anexar à observação, se houver."""
        erro = observacao.lstrip().upper().startswith(("ERRO", "ERROR", "PERMISSÃO NEGADA"))
        self._erros = self._erros + 1 if erro else 0
        self._obs.append(observacao[:500])
        if self._erros >= self.max_erros:
            self._erros = 0
            return t("guarda.erros_seguidos", n=self.max_erros)
        return None
