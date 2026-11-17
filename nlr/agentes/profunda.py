"""Pesquisa profunda em várias rodadas (nlr pesquisar --profunda, modo "pesquisa profunda" da interface).

1. PLANO: o modelo divide a pergunta em subperguntas (JSON validado; se falhar, usa variações simples).
2. RODADAS: para cada subpergunta, busca na web (ddgs/SearXNG, com cache e pausa contra limite de requisições)
   e, se pedido, na biblioteca; lê as páginas (trafilatura) e escreve um ACHADO curto com citações [n].
3. LACUNAS E CONTRADIÇÕES: o modelo aponta o que ficou sem resposta e onde as fontes discordam;
   as lacunas viram as subperguntas da próxima rodada (até a profundidade).
4. RELATÓRIO: seção por seção (cabe em contextos pequenos), introdução e conclusão; as citações são
   VERIFICADAS (número existe e a frase tem palavras em comum com o trecho citado); as inválidas são removidas.
5. Salva Markdown (e DOCX/PDF opcionais) na pasta de relatórios.
Profundidade e largura padrão vêm do perfil do modelo (pequeno 1x3, médio 2x4, grande 3x6).
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from ..erros import AgenteErro
from ..fontes import Fonte
from ..i18n import idioma_atual, instrucao_idioma
from ..llm.texto import estimar_tokens
from ..textutil import tokenizar

log = logging.getLogger(__name__)

PADROES = {"pequeno": (1, 3), "medio": (2, 4), "grande": (3, 6)}

P = {
    "pt": {
        "plano": "Você planeja pesquisas. Divida a pergunta em até {n} subperguntas objetivas e pesquisáveis na web "
                 "(cada uma cobre um aspecto diferente). Escreva cada subpergunta como consulta de busca curta.",
        "achado": "Responda à SUBPERGUNTA usando SOMENTE as FONTES. Cite cada afirmação com [n]. Seja factual e "
                  "conciso (até 150 palavras). Se as fontes não responderem, diga 'sem dados suficientes'.",
        "lacunas": "Você revisa uma pesquisa. Com base nos ACHADOS, liste: lacunas (perguntas importantes ainda sem "
                   "resposta, como consultas de busca curtas, no máximo {n}) e contradicoes (pontos em que as fontes "
                   "discordam). Listas vazias se não houver.",
        "secao": "Escreva a seção '{titulo}' de um relatório de pesquisa, em parágrafos, usando os ACHADOS e as "
                 "FONTES. Cite cada afirmação com [n] (só números que existem). Não invente.",
        "intro": "Escreva uma introdução (1 parágrafo) e uma conclusão (1-2 parágrafos, com limitações) para o "
                 "relatório sobre a PERGUNTA, a partir do RESUMO DAS SEÇÕES. Formato:\nINTRODUÇÃO:\n...\nCONCLUSÃO:\n...",
        "titulo": "Relatório de pesquisa", "fontes": "Fontes", "contr": "Contradições encontradas",
        "lac": "Lacunas que ficaram em aberto", "metodo": "Método", "intro_t": "Introdução", "concl_t": "Conclusão",
        "sem": "sem dados suficientes",
    },
    "en": {
        "plano": "You plan research. Split the question into up to {n} objective, web-searchable sub-questions "
                 "(each covering a different aspect). Write each one as a short search query.",
        "achado": "Answer the SUB-QUESTION using ONLY the SOURCES. Cite each claim with [n]. Be factual and concise "
                  "(up to 150 words). If the sources do not answer it, say 'not enough data'.",
        "lacunas": "You review research. Based on the FINDINGS, list: lacunas (important questions still unanswered, "
                   "as short search queries, at most {n}) and contradicoes (points where sources disagree). "
                   "Empty lists if none.",
        "secao": "Write the section '{titulo}' of a research report, in paragraphs, using the FINDINGS and SOURCES. "
                 "Cite each claim with [n] (only numbers that exist). Do not invent.",
        "intro": "Write an introduction (1 paragraph) and a conclusion (1-2 paragraphs, with limitations) for the "
                 "report on the QUESTION, from the SECTION SUMMARY. Format:\nINTRODUÇÃO:\n...\nCONCLUSÃO:\n...",
        "titulo": "Research report", "fontes": "Sources", "contr": "Contradictions found",
        "lac": "Open gaps", "metodo": "Method", "intro_t": "Introduction", "concl_t": "Conclusion",
        "sem": "not enough data",
    },
}


class Plano(BaseModel):
    subperguntas: List[str] = Field(default_factory=list)


class Revisao(BaseModel):
    lacunas: List[str] = Field(default_factory=list)
    contradicoes: List[str] = Field(default_factory=list)


@dataclass
class Achado:
    subpergunta: str
    rodada: int
    texto: str
    fontes: List[int] = field(default_factory=list)


@dataclass
class RelatorioProfundo:
    pergunta: str
    markdown: str
    fontes: List[Fonte]
    achados: List[Achado]
    contradicoes: List[str]
    lacunas: List[str]
    citacoes_removidas: int
    arquivos: List[str] = field(default_factory=list)
    rodadas: int = 0


def _p(chave: str, **kw) -> str:
    return P[idioma_atual()][chave].format(**kw)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def parametros(llm, profundidade: int = 0, largura: int = 0, cfg=None) -> tuple:
    nome = getattr(getattr(llm, "perfil", None), "nome", "medio")
    d, w = PADROES.get(nome, (2, 4))
    if cfg is not None:
        d = cfg.profunda.profundidade or d
        w = cfg.profunda.largura or w
    return max(1, min(5, profundidade or d)), max(1, min(8, largura or w))


_META = re.compile(r"^\s*(resposta|answer|claro|certo|aqui est[áa]|here is|segue)\b[^\n]{0,40}:\s*|"
                   r"^.{0,80}(pode ser escrita como|could be written as|can be written as)\s*:?\s*(\[\d+\])?\s*$", re.I | re.M)


def limpar_texto(txt: str) -> str:
    """Remove preâmbulos ("Resposta:", "A seção X pode ser escrita como:"), linhas só com [n] e repetições
    (modelos pequenos às vezes entram em laço repetindo a mesma frase)."""
    txt = _META.sub("", txt)
    vistas, linhas = set(), []
    for linha in txt.splitlines():
        if re.fullmatch(r"\s*(\[\d+\]\s*)+", linha):
            continue
        frases = re.split(r"(?<=[.!?])\s+", linha)
        novas = []
        for fr in frases:
            k = re.sub(r"\[\d+\]|\W+", " ", _norm(fr)).strip()
            if len(k) > 15 and k in vistas:
                continue
            vistas.add(k)
            novas.append(fr)
        nova = " ".join(novas).rstrip()
        if nova or (linhas and linhas[-1]):
            linhas.append(nova)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()


def atribuir_citacoes(texto: str, candidatas: List[Fonte], min_comuns: int = 3, fracao: float = 0.3) -> str:
    """Para frases SEM citação, acha a fonte (entre as usadas) com mais palavras em comum e cita [n].
    Modelos pequenos costumam esquecer de citar; a atribuição só acontece se a sobreposição for real."""
    if not candidatas:
        return texto
    vocab = [(f.n, set(tokenizar(_norm(f.titulo + " " + f.texto)))) for f in candidatas]
    saida = []
    for linha in texto.split("\n"):
        frases = re.split(r"(?<=[.!?])\s+", linha)
        novas = []
        for fr in frases:
            if re.search(r"\[\d+\]", fr) or len(fr) < 25:
                novas.append(fr)
                continue
            pal = {w for w in tokenizar(_norm(fr)) if len(w) > 3}
            if not pal:
                novas.append(fr)
                continue
            n, comuns = max(((n, len(pal & v)) for n, v in vocab), key=lambda x: x[1])
            if comuns >= min_comuns and comuns / len(pal) >= fracao:
                fr = re.sub(r"([.!?]?)$", lambda m: f" [{n}]{m.group(1)}", fr.rstrip(), count=1)
            novas.append(fr)
        saida.append(" ".join(novas))
    return "\n".join(saida)


def verificar_citacoes(texto: str, fontes: Dict[int, Fonte], min_comuns: int = 2) -> tuple:
    """Remove [n] inexistentes e [n] cuja frase não tem nenhuma palavra relevante em comum com o trecho citado."""
    removidas = 0
    vocab = {n: set(tokenizar(_norm(f.titulo + " " + f.texto))) for n, f in fontes.items()}
    frases = re.split(r"(?<=[.!?])\s+", texto)
    out = []
    for fr in frases:
        palavras = {w for w in tokenizar(_norm(re.sub(r"\[\d+\]", "", fr))) if len(w) > 3}

        def troca(m):
            nonlocal removidas
            n = int(m.group(1))
            if n not in fontes:
                removidas += 1
                return ""
            if palavras and len(palavras & vocab[n]) < min(min_comuns, len(palavras)):
                removidas += 1
                return ""
            return m.group(0)

        out.append(re.sub(r"\[(\d+)\]", troca, fr))
    return " ".join(out).replace(" .", "."), removidas


class PesquisaProfunda:
    def __init__(self, ctx, progresso: Optional[Callable[[dict], None]] = None):
        self.ctx = ctx
        self.llm = ctx.llm
        self.cfg = ctx.cfg
        self.progresso = progresso or (lambda d: None)
        self.fontes: Dict[int, Fonte] = {}
        self.urls: Dict[str, int] = {}

    def _ev(self, etapa: str, **kw):
        d = {"etapa": etapa, **kw}
        self.progresso(d)
        self.ctx.evento("progresso", f"{etapa}: {kw.get('msg', '')}")

    # ------------------------------------------------------------ etapas
    def planejar(self, pergunta: str, largura: int) -> List[str]:
        try:
            r = self.llm.chat_json([{"role": "system", "content": _p("plano", n=largura)},
                                    {"role": "user", "content": pergunta}], Plano, max_tokens=400, tentativas=2)
            subs = [s.strip()[:160] for s in r.subperguntas if s and s.strip()]
        except AgenteErro:
            subs = []
        vistos, out = set(), []
        for s in subs + [pergunta]:
            k = _norm(s)
            if k not in vistos:
                vistos.add(k)
                out.append(s)
        return out[:largura] or [pergunta]

    def _coletar(self, consulta: str, usar_web: bool, usar_biblioteca: bool) -> List[Fonte]:
        novas: List[Fonte] = []
        if usar_web:
            try:
                for f in self.ctx.web.pesquisar(consulta, inicio=len(self.fontes) + 1):
                    if f.referencia in self.urls:
                        novas.append(self.fontes[self.urls[f.referencia]])
                        continue
                    f.n = len(self.fontes) + 1
                    self.fontes[f.n] = f
                    self.urls[f.referencia] = f.n
                    novas.append(f)
            except AgenteErro as e:
                self._ev("aviso", msg=f"web: {e}")
            time.sleep(max(0.0, self.cfg.profunda.pausa_segundos))
        if usar_biblioteca:
            try:
                from ..biblioteca.busca import buscar

                for r in buscar(self.ctx.indice, consulta)[:4]:
                    chave = f"{r.caminho}#{r.local}"
                    if chave in self.urls:
                        novas.append(self.fontes[self.urls[chave]])
                        continue
                    f = Fonte(len(self.fontes) + 1, "biblioteca", r.rotulo.split(" (")[0], r.caminho, r.texto, r.local)
                    self.fontes[f.n] = f
                    self.urls[chave] = f.n
                    novas.append(f)
            except AgenteErro as e:
                self._ev("aviso", msg=f"biblioteca: {e}")
        return novas

    def _blocos(self, fontes: List[Fonte], fracao: float = 0.5) -> str:
        orc = int(self.cfg.modelo.contexto_tokens * fracao)
        blocos, usados = [], 0
        lim = 1400 if self.cfg.modelo.contexto_tokens > 6000 else 700
        for f in fontes:
            b = f.bloco(lim)
            t = estimar_tokens(b)
            if usados + t > orc and blocos:
                break
            blocos.append(b)
            usados += t
        return "\n\n".join(blocos)

    def achar(self, sub: str, fontes: List[Fonte], rodada: int) -> Achado:
        if not fontes:
            return Achado(sub, rodada, _p("sem"), [])
        msgs = [{"role": "system", "content": _p("achado") + "\n" + instrucao_idioma()},
                {"role": "user", "content": f"FONTES:\n{self._blocos(fontes)}\n\nSUBPERGUNTA: {sub}"}]
        try:
            txt = self.llm.chat(msgs, max_tokens=400, temperatura=0.2)
        except AgenteErro as e:
            txt = f"({e})"
        txt, _ = verificar_citacoes(limpar_texto(txt), self.fontes)
        if _p("sem") not in txt.lower():
            txt = atribuir_citacoes(txt, fontes)
        return Achado(sub, rodada, txt.strip(), sorted({int(x) for x in re.findall(r"\[(\d+)\]", txt)}))

    def revisar(self, pergunta: str, achados: List[Achado], largura: int) -> Revisao:
        resumo = "\n".join(f"- {a.subpergunta}: {a.texto[:500]}" for a in achados)
        try:
            r = self.llm.chat_json([{"role": "system", "content": _p("lacunas", n=largura)},
                                    {"role": "user", "content": f"PERGUNTA: {pergunta}\n\nACHADOS:\n{resumo}"}],
                                   Revisao, max_tokens=400, tentativas=2)
        except AgenteErro:
            return Revisao()
        feitas = {_norm(a.subpergunta) for a in achados}
        r.lacunas = [x[:160] for x in r.lacunas if x.strip() and _norm(x) not in feitas][:largura]
        r.contradicoes = [x for x in r.contradicoes if x.strip()][:6]
        return r

    def secao(self, titulo: str, achados: List[Achado]) -> str:
        nums = sorted({n for a in achados for n in a.fontes})
        fontes = [self.fontes[n] for n in nums if n in self.fontes]
        ach = "\n".join(f"- {a.texto}" for a in achados)
        msgs = [{"role": "system", "content": _p("secao", titulo=titulo) + "\n" + instrucao_idioma()},
                {"role": "user", "content": f"ACHADOS:\n{ach}\n\nFONTES:\n{self._blocos(fontes, 0.4)}"}]
        try:
            txt = self.llm.chat(msgs, max_tokens=min(900, self.cfg.modelo.max_tokens), temperatura=0.3)
        except AgenteErro:
            txt = ach
        return atribuir_citacoes(limpar_texto(txt), fontes)

    # ------------------------------------------------------------ execução
    def executar(self, pergunta: str, profundidade: int = 0, largura: int = 0, usar_web: bool = True,
                 usar_biblioteca: bool = False, salvar: bool = True) -> RelatorioProfundo:
        prof, larg = parametros(self.llm, profundidade, largura, self.cfg)
        self._ev("inicio", msg=pergunta, profundidade=prof, largura=larg)
        subs = self.planejar(pergunta, larg)
        self._ev("plano", msg=" | ".join(subs), subperguntas=subs)
        achados: List[Achado] = []
        contradicoes: List[str] = []
        lacunas: List[str] = []
        rodada = 0
        for rodada in range(1, prof + 1):
            for i, sub in enumerate(subs, 1):
                self._ev("busca", msg=sub, rodada=rodada, i=i, total=len(subs))
                fontes = self._coletar(sub, usar_web, usar_biblioteca)
                a = self.achar(sub, fontes, rodada)
                achados.append(a)
                self._ev("achado", msg=a.texto[:200], subpergunta=sub, fontes=a.fontes)
            rev = self.revisar(pergunta, achados, larg)
            contradicoes += [c for c in rev.contradicoes if c not in contradicoes]
            lacunas = rev.lacunas
            self._ev("revisao", msg=f"{len(rev.lacunas)} lacuna(s), {len(rev.contradicoes)} contradição(ões)",
                     lacunas=rev.lacunas, contradicoes=rev.contradicoes)
            if not rev.lacunas or rodada == prof:
                break
            subs = rev.lacunas
        rel = self.redigir(pergunta, achados, contradicoes, lacunas if rodada == prof else [], rodada)
        if salvar:
            rel.arquivos = salvar_relatorio(self.cfg, rel)
            self._ev("salvo", msg=", ".join(rel.arquivos), arquivos=rel.arquivos)
        self._ev("fim", msg=f"{len(rel.fontes)} fontes", fontes=len(rel.fontes))
        return rel

    def redigir(self, pergunta: str, achados: List[Achado], contradicoes: List[str], lacunas: List[str],
                rodadas: int) -> RelatorioProfundo:
        self._ev("redacao", msg=f"{len(achados)} achados")
        uteis = [a for a in achados if a.fontes]
        secoes = []
        grupos: Dict[str, List[Achado]] = {}
        for a in uteis:
            grupos.setdefault(a.subpergunta, []).append(a)
        for titulo, grupo in grupos.items():
            self._ev("secao", msg=titulo)
            secoes.append((titulo[:1].upper() + titulo[1:], self.secao(titulo, grupo)))
        corpo_resumo = "\n".join(f"## {t}\n{x[:600]}" for t, x in secoes)
        intro, concl = "", ""
        try:
            if not secoes:
                raise AgenteErro("sem seções")  # sem achados com fonte: não deixa o modelo inventar intro/conclusão
            ic = self.llm.chat([{"role": "system", "content": _p("intro") + "\n" + instrucao_idioma()},
                                {"role": "user", "content": f"PERGUNTA: {pergunta}\n\nRESUMO DAS SEÇÕES:\n{corpo_resumo}"}],
                               max_tokens=600, temperatura=0.3)
            m = re.split(r"CONCLUS[ÃA]O\s*:|CONCLUSION\s*:", ic, flags=re.I)
            intro = limpar_texto(re.sub(r"^\s*(INTRODU[ÇC][ÃA]O|INTRODUCTION)\s*:\s*", "", m[0].strip(), flags=re.I))
            concl = limpar_texto(m[1]) if len(m) > 1 else ""
        except AgenteErro:
            pass
        removidas = 0
        partes = [f"# {_p('titulo')}: {pergunta}\n"]
        if intro:
            partes += [f"## {_p('intro_t')}\n", re.sub(r"\[\d+\]", "", intro) + "\n"]
        for t, x in secoes:
            x, r = verificar_citacoes(x, self.fontes)
            removidas += r
            partes += [f"## {t}\n", x + "\n"]
        if contradicoes:
            partes += [f"## {_p('contr')}\n", "\n".join(f"- {c}" for c in contradicoes) + "\n"]
        if lacunas:
            partes += [f"## {_p('lac')}\n", "\n".join(f"- {c}" for c in lacunas) + "\n"]
        if concl:
            partes += [f"## {_p('concl_t')}\n", re.sub(r"\[\d+\]", "", concl) + "\n"]
        citadas = sorted({int(n) for n in re.findall(r"\[(\d+)\]", "\n".join(partes)) if int(n) in self.fontes})
        # renumera só as citadas, em ordem de aparição: [1]..[k]
        ordem: List[int] = []
        for n in re.findall(r"\[(\d+)\]", "\n".join(partes)):
            if int(n) in self.fontes and int(n) not in ordem:
                ordem.append(int(n))
        mapa = {old: i + 1 for i, old in enumerate(ordem)}
        md = re.sub(r"\[(\d+)\]", lambda m: f"[{mapa[int(m.group(1))]}]" if int(m.group(1)) in mapa else "",
                    "\n".join(partes))
        fontes_finais = []
        for old in ordem:
            f = self.fontes[old]
            fontes_finais.append(Fonte(mapa[old], f.tipo, f.titulo, f.referencia, f.texto, f.local))
        md += f"\n## {_p('fontes')}\n" + "\n".join(
            f"{f.n}. [{f.titulo}]({f.referencia})" if f.tipo == "web" else f"{f.n}. {f.titulo} {f.local}".strip()
            for f in fontes_finais) + "\n"
        md += (f"\n## {_p('metodo')}\n- rodadas: {rodadas}; subperguntas: {len(achados)}; fontes lidas: "
               f"{len(self.fontes)}; citadas: {len(citadas)}; citações removidas na verificação: {removidas}\n")
        return RelatorioProfundo(pergunta, md, fontes_finais, achados, contradicoes, lacunas, removidas, rodadas=rodadas)


def _nome_arquivo(pergunta: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", _norm(pergunta))[:60].strip("-") or "pesquisa"
    return time.strftime("%Y%m%d-%H%M-") + base


def salvar_relatorio(cfg, rel: RelatorioProfundo) -> List[str]:
    pasta = cfg.resolver(cfg.profunda.pasta_relatorios)
    pasta.mkdir(parents=True, exist_ok=True)
    nome = _nome_arquivo(rel.pergunta)
    arquivos = []
    md = pasta / f"{nome}.md"
    md.write_text(rel.markdown, encoding="utf-8")
    arquivos.append(str(md))
    fmts = {f.lower() for f in cfg.profunda.formatos}
    if "docx" in fmts:
        try:
            arquivos.append(str(_docx(rel.markdown, pasta / f"{nome}.docx")))
        except Exception as e:  # noqa: BLE001
            log.warning("DOCX não gerado: %s", e)
    if "abnt" in fmts:
        try:
            from ..kits import abnt as A

            k = cfg.kits.abnt
            trab = A.Trabalho(titulo=rel.pergunta, autor=k.autor or "Autor", instituicao=k.instituicao, curso=k.curso,
                              local=k.local, fonte=k.fonte,
                              natureza="Relatório de pesquisa gerado pelo Neuron Local Research (revise antes de entregar).")
            caminho, _ = A.relatorio_abnt(rel, pasta / f"{nome}-abnt.docx", trab, k.buscar_online, k.norma_citacao)
            arquivos.append(str(caminho))
        except Exception as e:  # noqa: BLE001
            log.warning("DOCX ABNT não gerado: %s", e)
    if "pdf" in fmts:
        try:
            arquivos.append(str(_pdf(rel.markdown, pasta / f"{nome}.pdf")))
        except Exception as e:  # noqa: BLE001
            log.warning("PDF não gerado (instale fpdf2): %s", e)
    return arquivos


def _docx(md: str, destino: Path) -> Path:
    from docx import Document

    doc = Document()
    for linha in md.splitlines():
        if linha.startswith("# "):
            doc.add_heading(linha[2:], 0)
        elif linha.startswith("## "):
            doc.add_heading(linha[3:], 1)
        elif linha.startswith("- "):
            doc.add_paragraph(linha[2:], style="List Bullet")
        elif linha.strip():
            doc.add_paragraph(re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", linha))
    doc.save(str(destino))
    return destino


def _pdf(md: str, destino: Path) -> Path:
    from fpdf import FPDF
    from fpdf.enums import WrapMode

    pdf = FPDF()
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()
    fonte = None
    for cand in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if Path(cand).exists():
            fonte = cand
            break
    if fonte:
        pdf.add_font("U", "", fonte)
        pdf.set_font("U", size=11)
    else:
        pdf.set_font("Helvetica", size=11)
    for linha in md.splitlines():
        txt = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", linha).lstrip("# ")
        if not fonte:
            txt = txt.encode("latin-1", "replace").decode("latin-1")
        tam = 16 if linha.startswith("# ") else 13 if linha.startswith("## ") else 11
        pdf.set_font_size(tam)
        pdf.multi_cell(0, 6 if tam == 11 else 8, txt or " ", new_x="LMARGIN", new_y="NEXT", wrapmode=WrapMode.CHAR)
    pdf.output(str(destino))
    return destino
