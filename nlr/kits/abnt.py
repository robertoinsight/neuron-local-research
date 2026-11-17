"""Kit ABNT (v0.6): referências NBR 6023:2018, citações NBR 10520:2023 (autor-data) e documento NBR 14724:2011.

* Metadados: DOI -> Crossref; ISBN -> OpenLibrary (fallback Google Books); URL -> metatags (citation_*, Dublin
  Core, Open Graph, JSON-LD) da própria página. Sem internet, dá para montar a referência à mão (Referencia(...)).
* Nada aqui depende do modelo de linguagem: a formatação é determinística (funciona com modelo de qualquer tamanho).
* As normas exigem conferência humana: o NLR avisa quando falta um elemento essencial (autor, ano, local, editora).
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

MESES = ["jan.", "fev.", "mar.", "abr.", "maio", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez."]
UA = {"User-Agent": "NeuronLocalResearch/0.6 (mailto:nlr@localhost)"}
PARTICULAS = {"de", "da", "do", "das", "dos", "e", "van", "von", "der", "den", "del", "la", "le", "di", "du"}
SUFIXOS = {"junior", "júnior", "jr", "jr.", "filho", "neto", "sobrinho", "segundo"}


# ------------------------------------------------------------------ modelo
@dataclass
class Autor:
    sobrenome: str
    prenomes: str = ""
    entidade: bool = False  # autor institucional (ex.: UNIVERSIDADE DE SÃO PAULO)

    def referencia(self) -> str:
        if self.entidade:
            return self.sobrenome.upper()
        return f"{self.sobrenome.upper()}, {self.prenomes}".strip().rstrip(",") if self.prenomes else self.sobrenome.upper()

    @staticmethod
    def de_nome(nome: str) -> "Autor":
        """'Maria Clara de Souza Filho' -> SOUZA FILHO, Maria Clara de. 'Souza, Maria' é respeitado."""
        nome = " ".join((nome or "").split())
        if "," in nome:
            sob, pre = [x.strip() for x in nome.split(",", 1)]
            return Autor(sob, pre)
        p = nome.split()
        if len(p) <= 1:
            return Autor(nome)
        sob = [p.pop()]
        if sob[0].lower().strip(".") in SUFIXOS and p:
            sob.insert(0, p.pop())
        return Autor(" ".join(sob), " ".join(p))


@dataclass
class Referencia:
    tipo: str = "site"  # livro | artigo | capitulo | site | trabalho_academico | relatorio
    autores: List[Autor] = field(default_factory=list)
    titulo: str = ""
    subtitulo: str = ""
    periodico: str = ""  # artigo: revista; capítulo: título do livro
    organizadores: List[Autor] = field(default_factory=list)
    edicao: str = ""
    local: str = ""
    editora: str = ""
    ano: str = ""
    volume: str = ""
    numero: str = ""
    paginas: str = ""
    doi: str = ""
    isbn: str = ""
    url: str = ""
    acesso: str = ""  # AAAA-MM-DD
    natureza: str = ""  # trabalho acadêmico: "Dissertação (Mestrado em X)"
    instituicao: str = ""
    avisos: List[str] = field(default_factory=list)

    def dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def de_dict(d: dict) -> "Referencia":
        d = dict(d)
        d["autores"] = [Autor(**a) if isinstance(a, dict) else Autor.de_nome(str(a)) for a in d.get("autores") or []]
        d["organizadores"] = [Autor(**a) if isinstance(a, dict) else Autor.de_nome(str(a)) for a in d.get("organizadores") or []]
        campos = Referencia.__dataclass_fields__
        return Referencia(**{k: v for k, v in d.items() if k in campos})


# ------------------------------------------------------------------ utilidades
def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def data_acesso(iso: str = "") -> str:
    d = _dt.date.fromisoformat(iso) if iso else _dt.date.today()
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


def normalizar_doi(s: str) -> str:
    m = re.search(r"10\.\d{4,9}/[^\s\"<>]+", s or "")
    return m.group(0).rstrip(".,;)") if m else ""


def normalizar_isbn(s: str) -> str:
    d = re.sub(r"[^0-9Xx]", "", s or "").upper()
    return d if len(d) in (10, 13) else ""


def isbn_valido(isbn: str) -> bool:
    isbn = normalizar_isbn(isbn)
    if len(isbn) == 10:
        tot = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(isbn))
        return tot % 11 == 0
    if len(isbn) == 13 and isbn.isdigit():
        return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(isbn)) % 10 == 0
    return False


def _paginas(p: str) -> str:
    p = (p or "").replace("--", "-").replace("–", "-").strip()
    return p


def _titulo_entrada(titulo: str) -> str:
    """Sem autor: a entrada é pelo título, com a 1ª palavra (e artigo inicial) em maiúsculas (NBR 6023, 8.1.1.8)."""
    p = titulo.split()
    if not p:
        return ""
    n = 2 if p[0].lower() in {"o", "a", "os", "as", "um", "uma", "the", "an", "a", "el", "la", "le"} and len(p) > 1 else 1
    return " ".join([w.upper() for w in p[:n]] + p[n:])


# ------------------------------------------------------------------ NBR 6023 (referências)
def autores_ref(autores: Sequence[Autor], max_autores: int = 3) -> str:
    """Até 3 autores separados por '; '. Mais de 3: todos ou o 1º + et al. (a norma permite os dois)."""
    if not autores:
        return ""
    if len(autores) > max_autores:
        return autores[0].referencia() + " et al."
    return "; ".join(a.referencia() for a in autores)


def _titulo_sub(ref: Referencia, destaque: bool) -> str:
    t = ref.titulo.strip().rstrip(".")
    if destaque:
        t = f"**{t}**"
    if ref.subtitulo:
        t += f": {ref.subtitulo.strip().rstrip('.')}"
    return t


def _publicacao(ref: Referencia) -> str:
    local = ref.local or "[S. l.]"
    editora = ref.editora or "[s. n.]"
    ano = ref.ano or "[20--]"
    return f"{local}: {editora}, {ano}"


def formatar_referencia(ref: Referencia, max_autores: int = 3) -> str:
    """Referência em markdown (**negrito** = destaque tipográfico). Elementos ausentes geram avisos em ref.avisos."""
    ref.avisos = []
    aut = autores_ref(ref.autores, max_autores)
    if not ref.titulo:
        ref.avisos.append("título ausente")
    if not ref.ano:
        ref.avisos.append("ano ausente (use a data provável entre colchetes, ex.: [2020?])")
    partes: List[str] = []
    tipo = ref.tipo
    if tipo == "artigo":
        ent = f"{aut}. " if aut else ""
        tit = _titulo_sub(ref, False) if aut else _titulo_entrada(_titulo_sub(ref, False))
        s = f"{ent}{tit}. **{ref.periodico.strip().rstrip('.')}**" if ref.periodico else f"{ent}{tit}."
        if not ref.periodico:
            ref.avisos.append("nome do periódico ausente")
        extra = [x for x in (ref.local, f"v. {ref.volume}" if ref.volume else "", f"n. {ref.numero}" if ref.numero else "",
                             f"p. {_paginas(ref.paginas)}" if ref.paginas else "", ref.ano or "[20--]") if x]
        s += ", " + ", ".join(extra) + "."
        partes.append(s)
    elif tipo == "capitulo":
        ent = f"{aut}. " if aut else ""
        org = autores_ref(ref.organizadores)
        org_txt = f"{org} (org.). " if org else ""
        s = f"{ent}{_titulo_sub(Referencia(titulo=ref.titulo, subtitulo=ref.subtitulo), False)}. In: {org_txt}**{ref.periodico.rstrip('.')}**."
        if ref.edicao:
            s += f" {ref.edicao}."
        s += f" {_publicacao(ref)}."
        if ref.paginas:
            s += f" p. {_paginas(ref.paginas)}."
        partes.append(s)
    elif tipo == "trabalho_academico":
        s = f"{aut}. {_titulo_sub(ref, True)}. {ref.ano or '[20--]'}."
        if ref.natureza:
            s += f" {ref.natureza} –"
        s += f" {ref.instituicao or '[instituição]'}, {ref.local or '[S. l.]'}, {ref.ano or '[20--]'}."
        partes.append(s)
    elif tipo in ("livro", "relatorio"):
        if aut:
            s = f"{aut}. {_titulo_sub(ref, True)}."
        else:
            s = f"{_titulo_entrada(_titulo_sub(ref, False))}."
        if ref.edicao:
            ed = ref.edicao if "ed" in ref.edicao else f"{ref.edicao}. ed"
            s += f" {ed.rstrip('.')}."
        s += f" {_publicacao(ref)}."
        if not ref.local:
            ref.avisos.append("local ausente ([S. l.])")
        if not ref.editora:
            ref.avisos.append("editora ausente ([s. n.])")
        partes.append(s)
    else:  # site / documento online
        if aut:
            s = f"{aut}. {_titulo_sub(ref, True)}."
        else:
            s = f"{_titulo_entrada(_titulo_sub(ref, False))}."
        if ref.periodico:
            s += f" {ref.periodico.rstrip('.')},"
            s = s.rstrip(",") + "."
        if ref.editora:
            s += f" {ref.local or '[S. l.]'}: {ref.editora}, {ref.ano or '[20--]'}."
        else:
            s += f" {ref.local or '[S. l.]'}, {ref.ano or '[20--]'}."
        partes.append(s)
    if ref.doi:
        partes.append(f"DOI: {ref.doi}.")
    if ref.url or tipo == "site":
        url = ref.url or (f"https://doi.org/{ref.doi}" if ref.doi else "")
        if url:
            partes.append(f"Disponível em: {url}. Acesso em: {data_acesso(ref.acesso)}.")
    texto = " ".join(partes)
    return re.sub(r"\s+", " ", texto).replace("..", ".").replace(". .", ".").strip()


def chave_ordenacao(ref: Referencia) -> str:
    """Ordem alfabética pela entrada (sobrenome ou título), sem acentos; desempate pelo ano."""
    base = autores_ref(ref.autores) or _titulo_entrada(ref.titulo)
    return _sem_acento(base).upper() + " " + (ref.ano or "")


def lista_referencias(refs: Sequence[Referencia]) -> List[str]:
    return [formatar_referencia(r) for r in sorted(refs, key=chave_ordenacao)]


# ------------------------------------------------------------------ NBR 10520 (citações, autor-data)
def _sobrenome_citacao(a: Autor, norma: str) -> str:
    s = a.sobrenome if not a.entidade else a.sobrenome
    if norma == "2002":
        return s.upper()
    # 2023: maiúsculas e minúsculas (entidades mantêm a grafia/sigla; "LeCun" fica como veio)
    if a.entidade or (s != s.upper() and s != s.lower()):
        return s
    return " ".join(w if w.lower() in PARTICULAS else w[:1].upper() + w[1:].lower() for w in s.split())


def citacao(ref: Referencia, pagina: str = "", narrativa: bool = False, norma: str = "2023") -> str:
    """(Silva, 2020, p. 15) | Silva (2020, p. 15) | (Silva; Souza, 2020) | (Silva et al., 2020).
    norma='2002' usa SOBRENOME em maiúsculas dentro dos parênteses (versão antiga, ainda pedida por alguns cursos)."""
    ano = ref.ano or "[20--]"
    if ref.autores:
        nomes = [_sobrenome_citacao(a, norma) for a in ref.autores]
        if len(nomes) > 3:
            quem = f"{nomes[0]} et al."
        else:
            quem = "; ".join(nomes)
    else:
        p = ref.titulo.split()
        quem = (p[0].upper() + (" ..." if len(p) > 1 else "")) if norma == "2002" else (p[0] + (" [...]" if len(p) > 1 else ""))
    loc = f", p. {pagina}" if pagina else ""
    if narrativa:
        q = quem
        if ref.autores and len(ref.autores) > 1 and len(ref.autores) <= 3:
            q = " e ".join([", ".join(nomes[:-1]), nomes[-1]]) if len(nomes) > 1 else nomes[0]
        if norma == "2002":
            q = " ".join(w[:1] + w[1:].lower() for w in q.split())
        return f"{q} ({ano}{loc})"
    return f"({quem}, {ano}{loc})"


def desambiguar_anos(refs: Sequence[Referencia]) -> None:
    """Mesmo autor e mesmo ano: acrescenta a, b, c (2020a, 2020b) — NBR 10520."""
    grupos: Dict[str, List[Referencia]] = {}
    for r in refs:
        chave = autores_ref(r.autores) + "|" + (r.ano or "")
        grupos.setdefault(chave, []).append(r)
    for lst in grupos.values():
        if len(lst) > 1 and lst[0].ano:
            for i, r in enumerate(sorted(lst, key=lambda x: x.titulo)):
                r.ano = f"{r.ano}{chr(97 + i)}"


# ------------------------------------------------------------------ metadados (internet)
def _get(url: str, timeout: float = 15.0, aceitar: str = "application/json"):
    import httpx

    r = httpx.get(url, headers={**UA, "Accept": aceitar}, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    return r


def de_crossref(item: dict) -> Referencia:
    tipo_cr = item.get("type", "")
    tipo = {"journal-article": "artigo", "book": "livro", "monograph": "livro", "edited-book": "livro",
            "book-chapter": "capitulo", "report": "relatorio", "dissertation": "trabalho_academico",
            "proceedings-article": "artigo", "posted-content": "site"}.get(tipo_cr, "artigo")
    autores = [Autor(a.get("family", "") or a.get("name", ""), a.get("given", ""), entidade="family" not in a)
               for a in item.get("author", []) if a.get("family") or a.get("name")]
    orgs = [Autor(a.get("family", ""), a.get("given", "")) for a in item.get("editor", []) if a.get("family")]
    data = (item.get("published-print") or item.get("published-online") or item.get("issued") or {}).get("date-parts", [[None]])
    ano = str(data[0][0]) if data and data[0] and data[0][0] else ""
    titulo = (item.get("title") or [""])[0]
    sub = (item.get("subtitle") or [""])[0] if item.get("subtitle") else ""
    if ":" in titulo and not sub:
        titulo, sub = [x.strip() for x in titulo.split(":", 1)]
    cont = (item.get("container-title") or [""])
    return Referencia(tipo=tipo, autores=autores, organizadores=orgs, titulo=_limpar_html(titulo), subtitulo=_limpar_html(sub),
                      periodico=_limpar_html(cont[0] if cont else ""), editora=item.get("publisher", "") if tipo != "artigo" else "",
                      local=item.get("publisher-location", "") if tipo != "artigo" else "", ano=ano,
                      volume=str(item.get("volume", "") or ""), numero=str(item.get("issue", "") or ""),
                      paginas=_paginas(str(item.get("page", "") or "")), doi=item.get("DOI", ""),
                      isbn=(item.get("ISBN") or [""])[0], edicao=str(item.get("edition-number", "") or ""))


def _limpar_html(s: str) -> str:
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", "", s or "")).split())


def de_doi(doi: str) -> Referencia:
    d = normalizar_doi(doi)
    if not d:
        raise ValueError(f"DOI inválido: {doi}")
    r = _get(f"https://api.crossref.org/works/{d}")
    ref = de_crossref(r.json()["message"])
    ref.doi = ref.doi or d
    return ref


def de_isbn(isbn: str) -> Referencia:
    i = normalizar_isbn(isbn)
    if not i:
        raise ValueError(f"ISBN inválido: {isbn}")
    try:
        d = _get(f"https://openlibrary.org/api/books?bibkeys=ISBN:{i}&format=json&jscmd=data").json()
        b = d.get(f"ISBN:{i}")
    except Exception:  # noqa: BLE001
        b = None
    if b:
        pubs = b.get("publishers") or [{}]
        locs = b.get("publish_places") or [{}]
        ano = re.search(r"\d{4}", b.get("publish_date", "") or "")
        return Referencia(tipo="livro", autores=[Autor.de_nome(a.get("name", "")) for a in b.get("authors", [])],
                          titulo=b.get("title", ""), subtitulo=b.get("subtitle", ""), editora=pubs[0].get("name", ""),
                          local=locs[0].get("name", ""), ano=ano.group(0) if ano else "", isbn=i,
                          paginas="", edicao="")
    g = _get(f"https://www.googleapis.com/books/v1/volumes?q=isbn:{i}").json()
    if not g.get("items"):
        raise ValueError(f"ISBN não encontrado no OpenLibrary nem no Google Books: {i}")
    v = g["items"][0]["volumeInfo"]
    ano = re.search(r"\d{4}", v.get("publishedDate", "") or "")
    return Referencia(tipo="livro", autores=[Autor.de_nome(a) for a in v.get("authors", [])], titulo=v.get("title", ""),
                      subtitulo=v.get("subtitle", ""), editora=v.get("publisher", ""), ano=ano.group(0) if ano else "",
                      isbn=i)


def metadados_html(html: str, url: str = "") -> Referencia:
    """Lê citation_* (Google Scholar), DC.*, og:*, article:*, JSON-LD e <title>."""
    metas: Dict[str, List[str]] = {}
    for m in re.finditer(r"<meta\s+[^>]*>", html, re.I):
        tag = m.group(0)
        k = re.search(r'(?:name|property|itemprop)\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        v = re.search(r'content\s*=\s*["\']([^"\']*)["\']', tag, re.I)
        if k and v:
            metas.setdefault(k.group(1).lower(), []).append(_html.unescape(v.group(1)).strip())

    def um(*ks):
        for k in ks:
            if metas.get(k) and metas[k][0]:
                return metas[k][0]
        return ""
    autores = metas.get("citation_author") or metas.get("dc.creator") or metas.get("author") or metas.get("article:author") or []
    ld_autor, ld_data, ld_tit, ld_pub = [], "", "", ""
    for bloco in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            j = json.loads(bloco.strip())
        except json.JSONDecodeError:
            continue
        for o in (j if isinstance(j, list) else j.get("@graph", [j]) if isinstance(j, dict) else []):
            if not isinstance(o, dict):
                continue
            a = o.get("author")
            for x in (a if isinstance(a, list) else [a] if a else []):
                nome = x.get("name") if isinstance(x, dict) else str(x)
                if nome:
                    ld_autor.append(nome)
            ld_data = ld_data or o.get("datePublished", "")
            ld_tit = ld_tit or o.get("headline", "")
            p = o.get("publisher")
            ld_pub = ld_pub or (p.get("name", "") if isinstance(p, dict) else "")
    autores = autores or ld_autor
    titulo = um("citation_title", "dc.title", "og:title", "twitter:title") or ld_tit
    if not titulo:
        t = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        titulo = _limpar_html(t.group(1)) if t else url
    data = um("citation_publication_date", "citation_date", "dc.date", "article:published_time", "date") or ld_data
    ano = re.search(r"(19|20)\d{2}", data or "")
    site = um("og:site_name", "citation_journal_title") or ld_pub
    doi = normalizar_doi(um("citation_doi", "dc.identifier", "prism.doi"))
    periodico = um("citation_journal_title")
    tipo = "artigo" if periodico else "site"
    nomes = []
    for a in autores:
        for n in re.split(r"\s*;\s*", a):
            if n and n.lower() not in {x.lower() for x in nomes} and not n.startswith("http"):
                nomes.append(n)
    titulo = _limpar_html(titulo)
    for suf in [site, "Wikipédia, a enciclopédia livre", "Wikipedia, the free encyclopedia"]:
        if suf:
            titulo = re.sub(r"\s+[–—|·-]\s+" + re.escape(suf) + r"\s*$", "", titulo)
    return Referencia(tipo=tipo, autores=[_autor_web(n) for n in nomes[:20]], titulo=titulo,
                      periodico=periodico or (site if tipo == "artigo" else ""), local="", ano=ano.group(0) if ano else "",
                      volume=um("citation_volume"), numero=um("citation_issue"),
                      paginas="-".join(x for x in (um("citation_firstpage"), um("citation_lastpage")) if x),
                      doi=doi, url=url, acesso=_dt.date.today().isoformat(),
                      editora=site if tipo == "site" else "")


_ENTIDADE = re.compile(r"\b(contribuidores|colaboradores|projetos|equipe|equipo|ltda|empresa|redação|redacao|team|staff|contributors|"
                       r"editors|editorial|universidade|university|instituto|institute|ministério|governo|associação)\b", re.I)


def _autor_web(nome: str) -> Autor:
    if _ENTIDADE.search(nome) or len(nome.split()) > 5:
        return Autor(nome, entidade=True)
    return Autor.de_nome(nome)


def de_url(url: str) -> Referencia:
    doi = normalizar_doi(url) if "doi.org/" in url else ""
    if doi:
        ref = de_doi(doi)
        ref.url = url
        ref.acesso = _dt.date.today().isoformat()
        return ref
    r = _get(url, aceitar="text/html,application/xhtml+xml")
    ref = metadados_html(r.text, url)
    if ref.doi and not ref.autores:
        try:
            ref2 = de_doi(ref.doi)
            ref2.url, ref2.acesso = url, ref.acesso
            return ref2
        except Exception:  # noqa: BLE001
            pass
    return ref


def identificar(texto: str) -> Referencia:
    """DOI, ISBN ou URL (detecta sozinho)."""
    s = texto.strip()
    if normalizar_doi(s) and ("doi" in s.lower() or s.startswith("10.")):
        return de_doi(s)
    if s.lower().startswith(("http://", "https://")):
        return de_url(s)
    if normalizar_isbn(s) and isbn_valido(s):
        return de_isbn(s)
    raise ValueError("Não reconheci DOI, ISBN ou URL em: " + s[:80])


# ------------------------------------------------------------------ biblioteca e fontes do NLR
def de_arquivo(caminho) -> Referencia:
    """Referência de um arquivo da biblioteca: DOI/ISBN no texto (1ªs páginas) -> internet; senão metadados do PDF/DOCX."""
    p = Path(caminho)
    texto, titulo, autor, ano = "", "", "", ""
    try:
        if p.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            r = PdfReader(str(p))
            texto = "\n".join((pg.extract_text() or "") for pg in r.pages[:3])
            md = r.metadata or {}
            titulo, autor = (md.get("/Title") or ""), (md.get("/Author") or "")
            ano = (re.search(r"(19|20)\d{2}", str(md.get("/CreationDate") or "")) or [""])[0] if md.get("/CreationDate") else ""
        elif p.suffix.lower() == ".docx":
            import docx

            d = docx.Document(str(p))
            texto = "\n".join(x.text for x in d.paragraphs[:80])
            cp = d.core_properties
            titulo, autor, ano = cp.title or "", cp.author or "", str(cp.created.year) if cp.created else ""
        else:
            texto = p.read_text(encoding="utf-8", errors="replace")[:8000]
    except Exception:  # noqa: BLE001
        pass
    doi = normalizar_doi(texto)
    if doi:
        try:
            return de_doi(doi)
        except Exception:  # noqa: BLE001
            pass
    m = re.search(r"ISBN[:\s-]*((?:97[89][-\s]?)?(?:\d[-\s]?){9}[\dXx])", texto)
    if m and isbn_valido(m.group(1)):
        try:
            return de_isbn(m.group(1))
        except Exception:  # noqa: BLE001
            pass
    ref = Referencia(tipo="livro" if p.suffix.lower() in (".pdf", ".docx") else "site",
                     autores=[Autor.de_nome(a) for a in re.split(r"\s*[;,&]\s*|\s+and\s+", autor) if a.strip()] if autor else [],
                     titulo=titulo or p.stem.replace("_", " ").replace("-", " "), ano=ano)
    ref.avisos.append("metadados do arquivo (confira autor, local e editora)")
    return ref


def de_fonte(fonte, buscar_online: bool = True) -> Referencia:
    """Fonte do NLR (web/biblioteca) -> Referencia. Web: metatags da página (se houver rede); senão título + URL."""
    if fonte.tipo == "web":
        if buscar_online:
            try:
                return de_url(fonte.referencia)
            except Exception:  # noqa: BLE001
                pass
        from urllib.parse import urlparse

        host = urlparse(fonte.referencia).netloc.replace("www.", "")
        return Referencia(tipo="site", titulo=fonte.titulo or host, editora=host, url=fonte.referencia,
                          acesso=_dt.date.today().isoformat())
    if fonte.tipo == "biblioteca" and Path(fonte.referencia).exists():
        return de_arquivo(fonte.referencia)
    return Referencia(tipo="site", titulo=fonte.titulo)


# ------------------------------------------------------------------ documento NBR 14724 (.docx)
@dataclass
class Trabalho:
    titulo: str
    autor: str
    instituicao: str = ""
    curso: str = ""
    subtitulo: str = ""
    natureza: str = ""  # ex.: "Trabalho de Conclusão de Curso apresentado ao curso de ... como requisito parcial ..."
    orientador: str = ""
    local: str = ""
    ano: str = ""
    fonte: str = "Times New Roman"  # ou "Arial"
    resumo: str = ""
    palavras_chave: str = ""


def _md_runs(par, texto: str, tamanho=None, fonte=None):
    """Escreve markdown simples (**negrito**, *itálico*, `código`) num parágrafo do python-docx."""
    from docx.shared import Pt

    for parte in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)", texto):
        if not parte:
            continue
        if parte.startswith("**") and parte.endswith("**"):
            r = par.add_run(parte[2:-2])
            r.bold = True
        elif parte.startswith("*") and parte.endswith("*") and len(parte) > 2:
            r = par.add_run(parte[1:-1])
            r.italic = True
        elif parte.startswith("`"):
            r = par.add_run(parte[1:-1])
        else:
            r = par.add_run(parte)
        if tamanho:
            r.font.size = Pt(tamanho)
        if fonte:
            r.font.name = fonte


def _campo(par, instrucao: str, texto_padrao: str = ""):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    for tipo, extra in (("begin", None), ("instr", instrucao), ("separate", None), ("texto", texto_padrao), ("end", None)):
        r = par.add_run()
        if tipo == "instr":
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = extra
            r._r.append(el)
        elif tipo == "texto":
            r.text = extra or ""
        else:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tipo)
            if tipo == "begin":
                el.set(qn("w:dirty"), "true")
            r._r.append(el)


def gerar_docx(trabalho: Trabalho, corpo_md: str, referencias: Sequence[Referencia], destino) -> Path:
    """Documento NBR 14724: A4; margens sup./esq. 3 cm e inf./dir. 2 cm; fonte 12 (citações longas, notas e
    legendas menores); espaçamento 1,5 (simples em citações longas e referências); recuo de 1ª linha 1,25 cm;
    capa, folha de rosto, [resumo], sumário (campo TOC do Word, atualiza ao abrir) e referências em ordem
    alfabética, alinhadas à esquerda, espaço simples e separadas por uma linha em branco. Títulos de seção
    primária em negrito/maiúsculas com indicativo numérico; títulos sem indicativo (SUMÁRIO, REFERÊNCIAS) centralizados.
    Paginação: contada desde a folha de rosto e mostrada (canto superior direito) a partir da parte textual."""
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    fonte = trabalho.fonte or "Times New Roman"
    ano = trabalho.ano or str(_dt.date.today().year)
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = fonte
    st.font.size = Pt(12)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), fonte)
    pf = st.paragraph_format
    pf.line_spacing = 1.5
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    for nome in ("Heading 1", "Heading 2", "Heading 3", "Title"):
        h = doc.styles[nome]
        h.font.name, h.font.size, h.font.color.rgb = fonte, Pt(12), None
        h.font.bold = True
        h.element.rPr.rFonts.set(qn("w:eastAsia"), fonte)
        h.paragraph_format.space_before, h.paragraph_format.space_after = Pt(0), Pt(18)  # 1 linha de 1,5 ~ 18pt
        h.paragraph_format.line_spacing = 1.5
        h.paragraph_format.keep_with_next = True
    doc.styles["Heading 2"].font.bold = False  # secundária: maiúsculas sem negrito
    doc.styles["Heading 3"].font.bold = True  # terciária: negrito, só a 1ª maiúscula

    def margens(sec):
        sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
        sec.top_margin, sec.left_margin, sec.bottom_margin, sec.right_margin = Cm(3), Cm(3), Cm(2), Cm(2)
        sec.header_distance = Cm(2)

    margens(doc.sections[0])

    def centro(texto, negrito=False, maiusc=False, antes=0):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        if antes:
            p.paragraph_format.space_before = Pt(antes)
        r = p.add_run(texto.upper() if maiusc else texto)
        r.bold = negrito
        return p

    def quebra():
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---- capa
    if trabalho.instituicao:
        centro(trabalho.instituicao, True, True)
    if trabalho.curso:
        centro(trabalho.curso, True, True)
    centro(trabalho.autor, False, True, antes=96)
    centro(trabalho.titulo + (":" if trabalho.subtitulo else ""), True, True, antes=180)
    if trabalho.subtitulo:
        centro(trabalho.subtitulo)
    centro(trabalho.local or "[Local]", antes=220)
    centro(ano)
    quebra()
    # ---- folha de rosto
    centro(trabalho.autor, False, True)
    centro(trabalho.titulo + (":" if trabalho.subtitulo else ""), True, True, antes=200)
    if trabalho.subtitulo:
        centro(trabalho.subtitulo)
    if trabalho.natureza:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(8)
        p.paragraph_format.space_before = Pt(60)
        p.paragraph_format.line_spacing = 1.0
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.add_run(trabalho.natureza)
        if trabalho.orientador:
            p2 = doc.add_paragraph()
            p2.paragraph_format.left_indent = Cm(8)
            p2.paragraph_format.space_before = Pt(12)
            p2.add_run(f"Orientador(a): {trabalho.orientador}")
    centro(trabalho.local or "[Local]", antes=160)
    centro(ano)
    quebra()
    # ---- resumo (opcional)
    if trabalho.resumo:
        centro("RESUMO", True)
        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = 1.0
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        _md_runs(p, trabalho.resumo)
        if trabalho.palavras_chave:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            r = p.add_run("Palavras-chave: ")
            r.bold = True
            p.add_run(trabalho.palavras_chave)
        quebra()
    # ---- sumário
    centro("SUMÁRIO", True)
    p = doc.add_paragraph()
    _campo(p, 'TOC \\o "1-3" \\h \\z \\u', "Clique com o botão direito e escolha 'Atualizar campo' para gerar o sumário.")
    estatico = [ln for ln in corpo_md.splitlines() if re.match(r"^#{1,3}\s", ln)]
    if estatico:  # prévia do sumário (vale mesmo sem atualizar o campo, ex.: LibreOffice)
        n = [0, 0, 0]
        for ln in estatico:
            nivel = len(ln) - len(ln.lstrip("#"))
            n[nivel - 1] += 1
            for k in range(nivel, 3):
                n[k] = 0
            num = ".".join(str(x) for x in n[:nivel])
            q = doc.add_paragraph()
            q.paragraph_format.first_line_indent = Cm(0)
            tit = ln.lstrip("#").strip()
            r = q.add_run(f"{num} {tit.upper() if nivel <= 2 else tit}")
            r.bold = nivel in (1, 3)
        q = doc.add_paragraph()
        r = q.add_run("REFERÊNCIAS")
        r.bold = True
    # ---- parte textual (nova seção com paginação visível)
    sec = doc.add_section(WD_SECTION.NEW_PAGE)
    margens(sec)
    sec.header.is_linked_to_previous = False
    pre = 2 + (1 if trabalho.resumo else 0)  # folha de rosto (+ resumo) + sumário; a capa não conta
    pg = OxmlElement("w:pgNumType")
    pg.set(qn("w:start"), str(pre + 1))
    sec._sectPr.append(pg)
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _campo(hp, "PAGE", str(pre + 1))
    for r in hp.runs:
        r.font.size = Pt(10)
    for s0 in doc.sections[:1]:
        s0.header.is_linked_to_previous = False
        s0.different_first_page_header_footer = False
    n = [0, 0, 0]
    primeira = True
    em_citacao = False
    for ln in corpo_md.splitlines():
        lin = ln.rstrip()
        m = re.match(r"^(#{1,3})\s+(.*)", lin)
        if m:
            nivel = len(m.group(1))
            n[nivel - 1] += 1
            for k in range(nivel, 3):
                n[k] = 0
            num = ".".join(str(x) for x in n[:nivel])
            tit = m.group(2).strip()
            if nivel == 1 and not primeira:
                doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)  # seção primária começa em página nova
            primeira = False
            h = doc.add_heading(f"{num} {tit.upper() if nivel <= 2 else tit}", level=nivel)
            h.paragraph_format.first_line_indent = Cm(0)
            continue
        if not lin.strip():
            em_citacao = False
            continue
        if lin.startswith("> "):  # citação direta longa: recuo 4 cm, fonte 10, espaço simples
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(4)
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.space_before = Pt(0 if em_citacao else 18)
            p.paragraph_format.space_after = Pt(18)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            _md_runs(p, lin[2:], tamanho=10)
            em_citacao = True
            continue
        if re.match(r"^\s*[-*]\s+", lin):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(1.25)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            _md_runs(p, "– " + re.sub(r"^\s*[-*]\s+", "", lin))
            continue
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(1.25)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        _md_runs(p, re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", lin))
    # ---- referências
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    h = doc.add_heading("REFERÊNCIAS", level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for ref_txt in lista_referencias(referencias):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.space_after = Pt(12)  # uma linha em branco (espaço simples) entre referências
        _md_runs(p, ref_txt)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc.save(destino)
    return destino


# ------------------------------------------------------------------ pesquisa profunda -> ABNT
def converter_citacoes(md: str, refs_por_n: Dict[int, Referencia], norma: str = "2023") -> str:
    """Troca [n] / [n, m] por (Autor, ano) e remove as seções que viram outra coisa no ABNT (Fontes/Referências)."""
    def troca(m):
        nums = [int(x) for x in re.findall(r"\d+", m.group(0))]
        cits = [citacao(refs_por_n[k], norma=norma)[1:-1] for k in nums if k in refs_por_n]
        return f"({'; '.join(dict.fromkeys(cits))})" if cits else ""
    md = re.split(r"\n#{1,3}\s*(?:Fontes|Referências|Sources|References)\s*\n", "\n" + md)[0].lstrip("\n")
    md = re.sub(r"\[(\d+(?:\s*[,;]\s*\d+)*)\](?!\()", troca, md)
    return re.sub(r"[ \t]+([.,;])", r"\1", md)


def relatorio_abnt(rel, destino, trabalho: Optional[Trabalho] = None, buscar_online: bool = True,
                   norma: str = "2023") -> Tuple[Path, List[Referencia]]:
    """RelatorioProfundo -> .docx ABNT (autor-data + referências NBR 6023). O título vira título da capa."""
    refs = {f.n: de_fonte(f, buscar_online) for f in rel.fontes}
    desambiguar_anos(list(refs.values()))
    md = rel.markdown
    titulo = rel.pergunta
    m = re.match(r"#\s+(.+)\n", md)
    if m:
        titulo = m.group(1).strip()
        md = md[m.end():]
    if not re.search(r"^#\s", md, re.M):  # relatório usa ## para seções: viram seções primárias
        md = re.sub(r"^#(#{1,3})\s", lambda m: m.group(1) + " ", md, flags=re.M)
    corpo = converter_citacoes(md, refs, norma)
    trab = trabalho or Trabalho(titulo=titulo, autor="Autor", local="", ano=str(_dt.date.today().year),
                                natureza="Relatório de pesquisa gerado pelo Neuron Local Research (revise antes de entregar).")
    usados = [refs[k] for k in sorted(refs)]
    return gerar_docx(trab, corpo, usados, destino), usados
