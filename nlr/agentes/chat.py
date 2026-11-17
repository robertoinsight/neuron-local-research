"""Conversa com memória: roteia cada mensagem (conversa, biblioteca, web, ambos, agente com ferramentas)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, List, Literal, Optional

from pydantic import BaseModel

from ..erros import AgenteErro
from ..fontes import Fonte
from ..i18n import instrucao_idioma, t
from ..llm.texto import estimar_tokens
from ..prompts import PAPEIS, PROMPT_CONVERSA, PROMPT_RESUMIR, PROMPT_ROTEADOR
from .pesquisa import pesquisar
from .react import AgenteReact

log = logging.getLogger(__name__)

MODOS = ("auto", "conversa", "biblioteca", "web", "ambos", "agente")


class Rota(BaseModel):
    rota: Literal["conversa", "biblioteca", "web", "ambos", "projeto"]


_PADROES = [
    ("ambos", r"(biblioteca|meus? (documentos|arquivos)).*(internet|web)|(internet|web).*(biblioteca|meus? (documentos|arquivos))|cruz(e|ar)|compar(e|ar) com a (web|internet)"),
    ("projeto", r"^(crie|desenvolva|construa|monte|implemente|programe|fa[çc]a) (um|uma) (projeto|programa|aplicativo|app|site|jogo|sistema|bot|script completo)"),
    ("web", r"\b(pesquis\w+|procure|busque)\b.*\b(internet|web|online|google)\b|\b(not[ií]cias?|hoje|atual(mente|izado)?|[uú]ltim[ao]s?|pre[çc]o|cota[çc][aã]o|lan[çc]amento|vers[aã]o mais recente|o que a web diz)\b"),
    ("biblioteca", r"\b(meus? (documentos|arquivos|pdfs?|anota[çc][oõ]es|c[oó]digos?|planilhas?)|minha biblioteca|nos meus|no meu arquivo|segundo (o|a) (documento|contrato|manual|planilha))\b"),
]


def rota_heuristica(msg: str) -> Optional[str]:
    m = msg.lower()
    for rota, padrao in _PADROES:
        if re.search(padrao, m):
            return rota
    return None


@dataclass
class RespostaChat:
    texto: str
    rota: str
    fontes: List[Fonte] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)
    sessao: str = ""


class SessaoChat:
    def __init__(self, serv, sessao_id: Optional[str] = None, eventos=None, confirmar=None):
        self.serv = serv
        self.cfg = serv.cfg
        self.memoria = serv.memoria
        if sessao_id and self.memoria.sessao_existe(sessao_id):
            self.id = sessao_id
        else:
            self.id = self.memoria.nova_sessao()
        self.workspace = self.cfg.dir_dados / "area_de_trabalho"
        self.ctx = serv.contexto(self.workspace, ["global"], "global", eventos=eventos, confirmar=confirmar)
        self._msgs_desde_extracao = 0
        from ..nucleo.handoff import GerenciadorHandoff

        self.handoff = GerenciadorHandoff(self.cfg, self.memoria, serv.llm)
        self.handoffs: List[str] = []

    def verificar_handoff(self, proxima: str = "") -> Optional[str]:
        """Se o chat passou de ~80% do contexto, continua num chat novo ligado a este. Devolve o aviso."""
        if not self.handoff.precisa(self.id, PROMPT_CONVERSA, proxima):
            return None
        u = self.handoff.uso(self.id)
        anterior = self.id
        self.id = self.handoff.executar(anterior)
        self.handoffs.append(self.id)
        aviso = t("handoff.iniciado", pct=round(u.fracao * 100), novo=self.id)
        self.ctx.evento("handoff", aviso)
        return aviso

    # ------------------------------------------------------------ histórico com resumo
    def _historico(self) -> List[dict]:
        hist = self.memoria.historico(self.id)
        resumo = self.memoria.resumo_sessao(self.id)
        orc = int(self.cfg.modelo.contexto_tokens * (0.9 if self.cfg.handoff.ativado else 0.35))
        if sum(estimar_tokens(m["content"]) for m in hist) > orc and len(hist) > 6:
            antigos, recentes = hist[:-6], hist[-6:]
            texto = (f"Resumo anterior:\n{resumo}\n\n" if resumo else "") + "\n".join(
                f"{m['role']}: {m['content'][:800]}" for m in antigos)
            try:
                resumo = self.serv.llm.chat([{"role": "system", "content": PROMPT_RESUMIR},
                                             {"role": "user", "content": texto}], max_tokens=500, temperatura=0.1)
                self.memoria.salvar_resumo(self.id, resumo)
            except AgenteErro:
                pass
            hist = recentes
        if resumo:
            hist = [{"role": "system", "content": f"Resumo da conversa até aqui:\n{resumo}"}] + hist
        return hist

    def rotear(self, mensagem: str) -> str:
        h = rota_heuristica(mensagem)
        if h:
            return h
        try:
            r = self.serv.llm.chat_json(
                [{"role": "system", "content": PROMPT_ROTEADOR},
                 {"role": "user", "content": f"Mensagem do usuário: {mensagem}"}], Rota, max_tokens=60, tentativas=2)
            return r.rota
        except AgenteErro:
            return "conversa"

    # ------------------------------------------------------------ resposta
    def responder(self, mensagem: str, modo: str = "auto", ao_receber: Optional[Callable[[str], None]] = None) -> RespostaChat:
        if modo not in MODOS:
            raise AgenteErro(f"Modo inválido: {modo}. Use: {', '.join(MODOS)}")
        aviso_handoff = self.verificar_handoff(mensagem)
        hist = self._historico()
        rota = self.rotear(mensagem) if modo == "auto" else modo
        self.ctx.evento("rota", rota)
        self.ctx.fontes = []
        avisos: List[str] = []
        fontes: List[Fonte] = []
        if rota == "projeto":
            texto = ("Isso parece um projeto completo. Para eu planejar, executar e revisar tudo de forma autônoma "
                     "(com estado salvo para retomar depois), use:\n\n"
                     f"    nlr projeto novo \"{mensagem[:120]}\"\n\n"
                     "ou, aqui no chat, digite /projeto seguido do objetivo.")
        elif rota in ("biblioteca", "web", "ambos"):
            r = pesquisar(self.ctx, mensagem, usar_biblioteca=rota in ("biblioteca", "ambos"),
                          usar_web=rota in ("web", "ambos"), historico=hist, ao_receber=ao_receber)
            texto, fontes, avisos = r.texto_completo(), r.fontes, r.avisos
            if ao_receber and r.fontes:
                ao_receber("\n\n**Fontes**\n" + "\n".join(f"- {f.cabecalho()}" for f in r.fontes))
        elif rota == "agente":
            ag = AgenteReact(self.serv.llm, self.serv.registro, self.ctx, PAPEIS["geral"],
                             max_passos=self.cfg.projetos.max_passos_por_tarefa)
            contexto = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in hist[-4:])
            res = ag.executar(f"Conversa recente:\n{contexto}\n\nTAREFA: {mensagem}" if contexto else f"TAREFA: {mensagem}")
            fontes = list(self.ctx.fontes)
            texto = res.resposta
            if fontes:
                texto += "\n\n**Fontes**\n" + "\n".join(f"- {f.cabecalho()}" for f in fontes)
            if ao_receber:
                ao_receber(texto)
        else:
            lembr = self.memoria.recordar(mensagem, self.escopos_memoria())
            sistema = PROMPT_CONVERSA + "\n" + instrucao_idioma()
            if lembr:
                sistema += ("\n\nLEMBRANÇAS (marcadas por origem; só [usuário: literal] é pedido/fato dito pelo usuário; "
                            "[inferido] é dedução sua, use com cautela):\n"
                            + "\n".join(f"- {x.rotulo()} {x.texto}" for x in lembr))
            msgs = [{"role": "system", "content": sistema}] + hist + [{"role": "user", "content": mensagem}]
            texto = self.serv.llm.chat(msgs, ao_receber=ao_receber)
        self.memoria.adicionar_mensagem(self.id, "user", mensagem)
        self.memoria.adicionar_mensagem(self.id, "assistant", texto)
        self._msgs_desde_extracao += 1
        if self.cfg.memoria.extrair_automaticamente and self._msgs_desde_extracao >= 4:
            self.extrair_memorias()
        if aviso_handoff:
            avisos.insert(0, aviso_handoff)
        return RespostaChat(texto=texto, rota=rota, fontes=fontes, avisos=avisos, sessao=self.id)

    # ------------------------------------------------------------ v0.7: imagens no chat
    def responder_imagem(self, mensagem: str, imagens: List, acao: str = "", marcadores: Optional[List[str]] = None,
                         ao_receber: Optional[Callable[[str], None]] = None) -> RespostaChat:
        """Mensagem com imagem(ns) anexada(s). acao: minucioso | geral | texto | pixel | pesquisar | "" (automático:
        com texto = responde à pergunta olhando a imagem; "pesquise na internet..." = pesquisa pela imagem)."""
        from ..ferramentas import visao

        if not imagens:
            return self.responder(mensagem, ao_receber=ao_receber)
        aviso_handoff = self.verificar_handoff(mensagem)
        msg = (mensagem or "").strip()
        if not acao:
            acao = "pesquisar" if msg and rota_heuristica(msg) == "web" else ("geral" if msg else self.cfg.visao.modo_padrao)
        self.ctx.fontes = []
        self.ctx.evento("rota", "imagem")
        fontes: List[Fonte] = []
        if acao == "pesquisar":
            r = visao.pesquisar(self.serv.llm, self.cfg, self.ctx.web, imagens[0], msg, ao_receber=ao_receber,
                                eventos=self.ctx.evento, adicionar_fontes=self.ctx.adicionar_fontes)
            fontes = r.fontes
            texto = r.texto
            if fontes and ao_receber:
                ao_receber("\n\n**Fontes**\n" + "\n".join(f"- {f.cabecalho()}" for f in fontes))
            if fontes:
                texto += "\n\n**Fontes**\n" + "\n".join(f"- {f.cabecalho()}" for f in fontes)
        else:
            hist = [{"role": m["role"], "content": str(m["content"])[:1500]} for m in self._historico()[-4:]
                    if m["role"] in ("user", "assistant")]
            r = visao.analisar(self.serv.llm, self.cfg, imagens, acao, msg, ao_receber=ao_receber,
                               eventos=self.ctx.evento, historico=hist)
            texto = r.texto
        rotulo = {"minucioso": "Analisar minuciosamente", "texto": "Ler texto", "pixel": "Revisar pixel art",
                  "pesquisar": "Pesquisar na internet pela imagem", "geral": "Descrever imagem"}.get(acao, acao)
        guardado = (msg or f"[{rotulo}]") + "".join(f"\n[imagem:{m}]" for m in (marcadores or []))
        self.memoria.adicionar_mensagem(self.id, "user", guardado)
        self.memoria.adicionar_mensagem(self.id, "assistant", texto)
        avisos = list(r.avisos)
        if aviso_handoff:
            avisos.insert(0, aviso_handoff)
        return RespostaChat(texto=texto, rota="imagem", fontes=fontes, avisos=avisos, sessao=self.id)

    def extrair_memorias(self) -> List[int]:
        if self._msgs_desde_extracao == 0:
            return []
        hist = self.memoria.historico(self.id, 8)
        texto = "\n".join(f"{'Usuário' if m['role'] == 'user' else 'Assistente'}: {m['content'][:1200]}" for m in hist)
        self._msgs_desde_extracao = 0
        literais = [m["content"] for m in hist if m["role"] == "user"]
        perfil = getattr(self.serv.llm, "perfil", None)
        if perfil is not None and getattr(perfil, "nome", "") == "pequeno":
            # modelos pequenos copiam os conselhos do assistente como "fatos": só o que o usuário escreveu
            texto = "\n".join(f"Usuário: {x[:1200]}" for x in literais)
        return self.memoria.extrair(self.serv.llm, texto, self.escopo_gravacao(), origem=f"sessao:{self.id}",
                                    msgs_usuario=literais)

    def escopo_gravacao(self) -> str:
        proj = self.memoria.projeto_sessao(self.id)
        return f"projeto:{proj}" if proj else "global"

    def escopos_memoria(self) -> List[str]:
        e = self.escopo_gravacao()
        return ["global"] if e == "global" else ["global", e]
