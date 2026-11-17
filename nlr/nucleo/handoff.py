"""Novo chat automático (handoff).

Quando a conversa chega a ~80% do contexto do modelo, o NLR:
  1. junta o ESTADO SALVO (resumo anterior, mensagens, lembranças da sessão, projeto ativo se houver);
  2. pede ao modelo um resumo de passagem (objetivo, decisões, o que foi feito, próximos passos);
     se o modelo falhar, usa um resumo extrativo (sem modelo) para nunca perder o fio;
  3. cria um chat novo LIGADO ao anterior (coluna `pai`), grava o resumo como mensagem de sistema e
     copia as 2 últimas mensagens, e continua dali.
Nada é apagado: o chat antigo fica no histórico e `cadeia_sessoes` mostra a sequência inteira.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, List, Optional

from ..erros import AgenteErro
from ..i18n import idioma_atual, t
from ..llm.texto import estimar_tokens

log = logging.getLogger(__name__)

PROMPT_HANDOFF = {
    "pt": ("Você vai passar esta conversa para um novo chat porque o contexto acabou. Escreva um RESUMO DE PASSAGEM "
           "completo e objetivo, com estas seções: Objetivo do usuário; Decisões e preferências; O que já foi feito "
           "(arquivos, resultados, fontes); Pendências e próximos passos; Detalhes que não podem se perder "
           "(nomes, números, caminhos). Máximo de 400 palavras."),
    "en": ("You are handing this conversation over to a new chat because the context is full. Write a complete, "
           "objective HANDOFF SUMMARY with these sections: User goal; Decisions and preferences; What was done "
           "(files, results, sources); Pending items and next steps; Details that must not be lost (names, numbers, "
           "paths). At most 400 words."),
}


def tokens_mensagens(msgs: List[dict]) -> int:
    return sum(estimar_tokens(m.get("content", "")) + 4 for m in msgs)


@dataclass
class Uso:
    tokens: int
    limite: int
    contexto: int

    @property
    def fracao(self) -> float:
        return self.tokens / self.contexto if self.contexto else 0.0


class GerenciadorHandoff:
    def __init__(self, cfg, memoria, llm, estado_extra: Optional[Callable[[str], str]] = None):
        self.cfg = cfg
        self.memoria = memoria
        self.llm = llm
        self.estado_extra = estado_extra

    def uso(self, sid: str, sistema: str = "", reserva_resposta: Optional[int] = None) -> Uso:
        hist = self.memoria.historico(sid, 10_000)
        resumo = self.memoria.resumo_sessao(sid)
        ctx = max(1024, int(self.cfg.modelo.contexto_tokens))
        reserva = reserva_resposta if reserva_resposta is not None else self.cfg.modelo.max_tokens
        total = tokens_mensagens(hist) + estimar_tokens(resumo) + estimar_tokens(sistema) + reserva
        return Uso(tokens=total, limite=int(ctx * self.cfg.handoff.limite), contexto=ctx)

    def precisa(self, sid: str, sistema: str = "", proxima: str = "") -> bool:
        if not self.cfg.handoff.ativado:
            return False
        u = self.uso(sid, sistema)
        return u.tokens + estimar_tokens(proxima) >= u.limite and self.memoria.total_mensagens(sid) >= 2

    # ------------------------------------------------------------ resumo
    def _material_base(self, sid: str) -> str:
        partes = []
        resumo = self.memoria.resumo_sessao(sid)
        if resumo:
            partes.append(f"[Resumo anterior]\n{resumo}")
        try:
            lembr = [x for x in self.memoria.listar(None, 50) if x.origem == f"sessao:{sid}"]
        except Exception:  # noqa: BLE001
            lembr = []
        if lembr:
            partes.append("[Lembranças desta conversa]\n" + "\n".join(f"- {x.texto}" for x in lembr))
        if self.estado_extra:
            extra = self.estado_extra(sid)
            if extra:
                partes.append(f"[Estado do projeto]\n{extra}")
        hist = [m for m in self.memoria.historico(sid, 10_000) if m["role"] != "system"]
        orc = int(self.cfg.modelo.contexto_tokens * 0.55) * 3  # caracteres ~ tokens*3.5, com folga
        linhas, usado = [], 0
        for m in reversed(hist):  # mais recentes primeiro, até caber
            linha = f"{m['role']}: {m['content'][:1500]}"
            if usado + len(linha) > orc:
                break
            linhas.append(linha)
            usado += len(linha)
        partes.append("[Mensagens]\n" + "\n".join(reversed(linhas)))
        return "\n\n".join(partes)

    def resumo_extrativo(self, sid: str) -> str:
        """Sem modelo: pedidos do usuário + finais das respostas. Garante continuidade mesmo se o LLM falhar."""
        hist = self.memoria.historico(sid, 10_000)
        pedidos = [m["content"][:300] for m in hist if m["role"] == "user"]
        resp = [m["content"][:400] for m in hist if m["role"] == "assistant"][-3:]
        anterior = self.memoria.resumo_sessao(sid)
        txt = (f"{anterior}\n\n" if anterior else "") + "Pedidos:\n" + "\n".join(f"- {p}" for p in pedidos[-12:])
        if resp:
            txt += "\n\nÚltimas respostas:\n" + "\n".join(f"- {r}" for r in resp)
        return txt

    def _ancoras(self, sid: str) -> str:
        """Primeiros pedidos do usuário, copiados LITERALMENTE: o objetivo e os nomes nunca se perdem,
        mesmo que o modelo pequeno resuma mal."""
        hist = self.memoria.historico(sid, 10_000)
        prim = [m["content"][:500] for m in hist if m["role"] == "user"][:2]
        anteriores = [m["content"] for m in hist if m["role"] == "system" and "[Pedidos originais]" in m["content"]]
        if anteriores:  # chat que já era continuação: herda as âncoras do primeiro chat
            return anteriores[0][anteriores[0].index("[Pedidos originais]"):]
        return "[Pedidos originais]\n" + "\n".join(f"- {p}" for p in prim) if prim else ""

    def _material(self, sid: str) -> str:
        return self._ancoras(sid) + "\n\n" + self._material_base(sid)

    def gerar_resumo(self, sid: str) -> str:
        material = self._material(sid)
        ancoras = self._ancoras(sid)
        try:
            r = self.llm.chat([{"role": "system", "content": PROMPT_HANDOFF[idioma_atual()]},
                               {"role": "user", "content": material}], max_tokens=700, temperatura=0.1).strip()
            r = r or self.resumo_extrativo(sid)
        except AgenteErro as e:
            log.warning("Handoff sem modelo (%s); usando resumo extrativo", e)
            r = self.resumo_extrativo(sid)
        return f"{r}\n\n{ancoras}".strip()

    # ------------------------------------------------------------ troca de chat
    def executar(self, sid: str) -> str:
        u = self.uso(sid)
        resumo = self.gerar_resumo(sid)
        titulo = self.memoria.titulo_sessao(sid) or "conversa"
        novo = self.memoria.nova_sessao(t("handoff.titulo", titulo=titulo)[:60], pai=sid)
        conteudo = f"{t('handoff.cabecalho', anterior=sid)}\n{resumo}"
        self.ultima_verificacao = None
        if getattr(self.cfg.handoff, "inhearsay", True):
            from . import inhearsay

            msgs_u = [m["content"] for m in self.memoria.historico(sid, 10_000) if m["role"] == "user"]
            anotado, v = inhearsay.anotar(resumo, msgs_u, idioma_atual())
            self.ultima_verificacao = v
            literais = "\n".join(f"- \"{m[:400]}\"" for m in msgs_u[-6:])
            titulo_lit = "MENSAGENS LITERAIS DO USUÁRIO (mais recentes)" if idioma_atual() == "pt" else \
                "VERBATIM USER MESSAGES (most recent)"
            conteudo = (f"{t('handoff.cabecalho', anterior=sid)}\n{anotado}\n\n{titulo_lit}:\n{literais}\n\n"
                        f"{inhearsay.REGRA[idioma_atual()]}\n(taxa de inhearsay: {v.taxa:.0%})")
            log.info("Inhearsay: %d de %d itens marcados", len(v.marcados), v.verificaveis)
        self.memoria.adicionar_mensagem(novo, "system", conteudo)
        self.memoria.salvar_resumo(sid, resumo)
        for m in [m for m in self.memoria.historico(sid, 4) if m["role"] in ("user", "assistant")][-2:]:
            self.memoria.adicionar_mensagem(novo, m["role"], m["content"][:3000])
        log.info("Handoff %s -> %s (%.0f%% do contexto)", sid, novo, u.fracao * 100)
        return novo
