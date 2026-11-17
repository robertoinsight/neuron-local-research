"""Pesquisa profunda determinística (funciona bem até com modelos pequenos):

1. gera variações da pergunta (JSON validado; se falhar, usa a própria pergunta);
2. busca na biblioteca (híbrida) e/ou na web (lendo as páginas);
3. junta lembranças relevantes da memória;
4. sintetiza a resposta com citações [n] e, quando há as duas origens, uma seção Biblioteca × Web;
5. anexa a lista de fontes de forma determinística (não depende do modelo).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from pydantic import BaseModel, Field

from ..biblioteca.busca import buscar
from ..erros import AgenteErro
from ..fontes import Fonte, lista_referencias
from ..llm.texto import estimar_tokens
from ..prompts import PROMPT_CRUZAMENTO, PROMPT_SINTESE, PROMPT_SUBCONSULTAS

log = logging.getLogger(__name__)


class Subconsultas(BaseModel):
    consultas: List[str] = Field(default_factory=list, max_length=3)


@dataclass
class ResultadoPesquisa:
    resposta: str
    fontes: List[Fonte] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)
    citacoes_invalidas: List[int] = field(default_factory=list)

    def texto_completo(self) -> str:
        resposta = limpar_lista_de_fontes(self.resposta)
        if not self.fontes:
            return resposta
        citadas = {int(n) for n in re.findall(r"\[(\d+)\]", resposta)}
        usadas = [f for f in self.fontes if f.n in citadas] or self.fontes
        texto = f"{resposta}\n\n**Fontes**\n" + "\n".join(f"- {f.cabecalho()}" for f in usadas)
        outras = len(self.fontes) - len(usadas)
        if outras:
            texto += f"\n\n_(+{outras} fonte(s) consultada(s) e não citada(s))_"
        return texto


_LISTA_FONTES_FINAL = re.compile(
    r"\n+[ \t]*(?:#+[ \t]*|\*\*)?(?:Fontes|Referências|Sources)(?:\*\*)?[ \t]*:?(?:\*\*)?[ \t]*\n"
    r"(?:[ \t]*(?:[-*•]|\[\d+\]|\d+\.)[^\n]*\n?|[ \t]*\n)*\Z", re.IGNORECASE)


def limpar_lista_de_fontes(texto: str) -> str:
    """Remove a lista de fontes que o modelo às vezes escreve no fim (a nossa é anexada automaticamente)."""
    return _LISTA_FONTES_FINAL.sub("", texto.rstrip() + "\n").rstrip()


_FONTES_PEDIDAS = r"(?:na|nas|no|nos|em|pela|pelo)\s+(?:minha|minhas|meu|meus)?\s*(?:biblioteca|documentos?|arquivos?|internet|web|rede)"
_PEDIDO_PESQUISA = re.compile(
    r"^\s*(?:por favor,?\s*)?(?:pesquis\w*|busqu\w*|procur\w*|investigu\w*|consult\w*)\s+"
    r"(?:" + _FONTES_PEDIDAS + r"(?:\s*(?:,|e)\s*" + _FONTES_PEDIDAS + r")*\s*)?(?:sobre|a respeito de|por)?\s*",
    re.IGNORECASE)
_PEDIDO_ACAO = re.compile(r"\s*(?:,|\.|;)?\s*\be\s+(?:depois\s+)?(?:desenvolv|cri|fa[çc]|escrev|implement|mont|gere|ger)\w*\b.*$",
                          re.IGNORECASE | re.S)


def consulta_limpa(pergunta: str) -> str:
    """Tira do pedido as instruções ("pesquise na minha biblioteca e na internet sobre ... e desenvolva ...")
    para sobrar só o assunto, que é o que deve ir para o buscador."""
    q = _PEDIDO_PESQUISA.sub("", pergunta.strip(), count=1)
    q2 = _PEDIDO_ACAO.sub("", q)
    q = q2 if len(q2) >= 8 else q
    q = q.strip(" .,:;?!")
    return (q or pergunta)[:200]


def gerar_subconsultas(llm, pergunta: str) -> List[str]:
    try:
        r = llm.chat_json([{"role": "system", "content": PROMPT_SUBCONSULTAS},
                           {"role": "user", "content": pergunta}], Subconsultas, max_tokens=200, tentativas=2)
        qs = [q.strip() for q in r.consultas if q and q.strip()]
    except AgenteErro as e:
        log.info("Subconsultas indisponíveis: %s", e)
        qs = []
    vistos, out = set(), []
    for q in qs:
        k = q.lower()
        if k not in vistos and k != pergunta.lower():
            vistos.add(k)
            out.append(q[:150])
    return out[:3]


def pesquisar(ctx, pergunta: str, usar_biblioteca: bool = True, usar_web: bool = True, historico: Optional[List[dict]] = None,
              ao_receber: Optional[Callable[[str], None]] = None, expandir: bool = True) -> ResultadoPesquisa:
    llm = ctx.llm
    cfg = ctx.cfg
    avisos: List[str] = []
    subs = gerar_subconsultas(llm, pergunta) if expandir else []
    if subs:
        ctx.evento("status", "Consultas: " + " | ".join(subs))
    fontes: List[Fonte] = []
    tem_bib = tem_web = False
    if usar_biblioteca:
        try:
            if ctx.indice.status()["trechos"] == 0:
                avisos.append("A biblioteca está vazia/não indexada (rode: nlr indexar).")
            else:
                ctx.evento("status", "Buscando na biblioteca...")
                res = buscar(ctx.indice, pergunta, consultas_extras=subs)
                for r in res:
                    fontes.append(Fonte(0, "biblioteca", r.rotulo.split(" (")[0], r.caminho, r.texto, r.local))
                tem_bib = bool(res)
        except AgenteErro as e:
            avisos.append(f"Biblioteca: {e}")
    if usar_web:
        consultas_web = ([subs[0]] if subs else []) + [consulta_limpa(pergunta)]
        vistos = set()
        for q in consultas_web[:2]:
            try:
                for f in ctx.web.pesquisar(q, status=lambda s: ctx.evento("status", s)):
                    if f.referencia not in vistos:
                        vistos.add(f.referencia)
                        fontes.append(f)
                        tem_web = True
            except AgenteErro as e:
                avisos.append(f"Web: {e}")
                break
    fontes = ctx.adicionar_fontes(fontes)
    lembrancas = []
    if ctx.memoria is not None:
        lembrancas = ctx.memoria.recordar(pergunta, ctx.escopos_memoria)
    if not fontes:
        msg = "Não encontrei fontes para responder."
        if avisos:
            msg += "\n" + "\n".join(f"- {a}" for a in avisos)
        return ResultadoPesquisa(msg, [], avisos)
    # orçamento de contexto: corta fontes que não cabem
    orc = int(cfg.modelo.contexto_tokens * 0.55)
    blocos, usados, usadas = [], 0, []
    for f in fontes:
        b = f.bloco(1600)
        t = estimar_tokens(b)
        if usados + t > orc and usadas:
            continue
        blocos.append(b)
        usadas.append(f)
        usados += t
    sistema = PROMPT_SINTESE + (PROMPT_CRUZAMENTO if (tem_bib and tem_web) else "")
    msgs = [{"role": "system", "content": sistema}]
    for m in (historico or [])[-6:]:
        msgs.append({"role": m["role"], "content": m["content"][:1500]})
    contexto_mem = ""
    if lembrancas:
        contexto_mem = "LEMBRANÇAS (memória do agente, sem número de fonte):\n" + "\n".join(f"- {x.texto}" for x in lembrancas) + "\n\n"
    msgs.append({"role": "user", "content": f"{contexto_mem}FONTES:\n\n" + "\n\n".join(blocos) + f"\n\nPERGUNTA: {pergunta}"})
    ctx.evento("status", f"Sintetizando a resposta com {len(usadas)} fonte(s)...")
    resposta = llm.chat(msgs, ao_receber=ao_receber)
    citadas = {int(x) for x in re.findall(r"\[(\d+)\]", resposta)}
    validos = {f.n for f in usadas}
    invalidas = sorted(citadas - validos)
    if invalidas:
        avisos.append(f"O modelo citou fonte(s) inexistente(s): {invalidas}.")
    return ResultadoPesquisa(resposta, usadas, avisos, invalidas)


def relatorio_markdown(pergunta: str, r: ResultadoPesquisa) -> str:
    partes = [f"# Pesquisa: {pergunta}\n", r.resposta, "\n## Fontes\n", lista_referencias(r.fontes)]
    if r.avisos:
        partes += ["\n## Avisos\n", "\n".join(f"- {a}" for a in r.avisos)]
    return "\n".join(partes) + "\n"
