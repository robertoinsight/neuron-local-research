"""Leitura dos formatos da biblioteca. Cada carregador devolve segmentos com a localização para citação.

Formatos: PDF, DOCX, TXT/MD/RST, CSV/TSV, XLSX, JSON, HTML e código-fonte (dezenas de extensões).
Novos formatos: registre uma função em CARREGADORES (veja docs/ESTENDER.md).
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List

from ..erros import AgenteErro


@dataclass
class Segmento:
    texto: str
    local: str = ""  # ex.: "p. 3", "linhas 10-42", "planilha Vendas, linhas 2-30"
    tipo: str = "texto"  # texto | codigo | tabela
    linha_inicial: int = 1  # para código: linha onde o segmento começa


EXT_CODIGO = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php",
    ".lua", ".gd", ".sh", ".ps1", ".sql", ".kt", ".swift", ".scala", ".r", ".m", ".dart", ".vue", ".svelte",
}
EXT_TEXTO = {".txt", ".md", ".markdown", ".rst", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log", ".tex"}


def ler_texto(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def carregar_texto(path: Path) -> List[Segmento]:
    return [Segmento(ler_texto(path))]


def carregar_codigo(path: Path) -> List[Segmento]:
    return [Segmento(ler_texto(path), tipo="codigo")]


# Opções definidas pelo índice a partir do config (OCR etc.) e avisos da última leitura.
OPCOES = {"ocr": "auto", "ocr_idiomas": "por+eng", "tabelas_pdf": True}
AVISOS: List[str] = []


def carregar_pdf(path: Path) -> List[Segmento]:
    from pypdf import PdfReader

    from . import documentos as D

    try:
        reader = PdfReader(str(path))
    except Exception as e:  # noqa: BLE001
        raise AgenteErro(f"PDF ilegível ({path.name}): {e}") from e
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:  # noqa: BLE001
            raise AgenteErro(f"PDF protegido por senha: {path.name}") from e
    tabelas = D.tabelas_pdf(str(path)) if OPCOES.get("tabelas_pdf", True) else {}
    segs: List[Segmento] = []
    escaneadas, sem_ocr = 0, 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            txt = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            txt = ""
        local = f"p. {i}"
        if D.pagina_parece_escaneada(txt, D.pagina_tem_imagem(page)):
            escaneadas += 1
            ocr = D.ocr_pagina(str(path), i - 1, page, OPCOES.get("ocr", "auto"), OPCOES.get("ocr_idiomas", "por+eng"))
            if ocr.strip():
                txt, local = ocr, f"p. {i} (OCR)"
            else:
                sem_ocr += 1
        if txt.strip():
            segs.append(Segmento(txt, local))
        for k, md in enumerate(tabelas.get(i, []), start=1):
            segs.append(Segmento(f"Tabela {k} da página {i}:\n{md}", f"p. {i}, tabela {k}", "tabela"))
    if escaneadas:
        AVISOS.append(f"{path.name}: {escaneadas} página(s) escaneada(s)"
                      + (f", {sem_ocr} sem OCR (instale: pip install rapidocr-onnxruntime)" if sem_ocr else ", lidas com OCR"))
    if not segs:
        raise AgenteErro(f"O PDF {path.name} não tem texto extraível (é escaneado e não há OCR instalado: "
                         f"pip install rapidocr-onnxruntime).")
    return segs


def carregar_docx(path: Path) -> List[Segmento]:
    """Percorre o corpo NA ORDEM (parágrafos e tabelas); títulos viram '#', tabelas viram markdown."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    from .documentos import tabela_markdown

    d = docx.Document(str(path))
    segs: List[Segmento] = []
    partes: List[str] = []
    ntab = 0
    titulo = ""
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(el, d)
            t = p.text.strip()
            if not t:
                continue
            estilo = (p.style.name or "").lower() if p.style is not None else ""
            if estilo.startswith(("heading", "título", "titulo", "title")):
                nivel = "".join(ch for ch in estilo if ch.isdigit())[:1] or "1"
                titulo = t
                partes.append("\n" + "#" * min(int(nivel), 4) + " " + t)
            else:
                partes.append(t)
        elif tag == "tbl":
            ntab += 1
            tb = Table(el, d)
            linhas = []
            for row in tb.rows:
                cel, vistos = [], set()
                for c in row.cells:  # células mescladas repetem o mesmo objeto
                    if id(c._tc) in vistos:
                        continue
                    vistos.add(id(c._tc))
                    cel.append(c.text.strip())
                linhas.append(cel)
            md = tabela_markdown(linhas)
            if md:
                if partes:
                    segs.append(Segmento("\n".join(partes)))
                    partes = []
                rot = f"tabela {ntab}" + (f" (seção {titulo})" if titulo else "")
                segs.append(Segmento(f"Tabela {ntab}" + (f" — {titulo}" if titulo else "") + f":\n{md}", rot, "tabela"))
    if partes:
        segs.append(Segmento("\n".join(partes)))
    return segs or [Segmento("")]


def _tabela_para_segmentos(nome: str, linhas: List[List[str]], max_chars: int = 1500) -> List[Segmento]:
    """Tabela -> blocos markdown com o cabeçalho repetido em cada bloco (bom para modelos pequenos)."""
    from .documentos import tabelas_markdown_em_blocos

    out = []
    for md, a, b in tabelas_markdown_em_blocos(linhas, max_chars):
        out.append(Segmento(f"{nome}:\n{md}", f"{nome}, linhas {a}-{b}" if b > 1 else nome, "tabela"))
    return out


def carregar_csv(path: Path) -> List[Segmento]:
    texto = ler_texto(path)
    try:
        dialeto = csv.Sniffer().sniff(texto[:5000], delimiters=",;\t|")
    except csv.Error:
        dialeto = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
    linhas = list(csv.reader(io.StringIO(texto), dialeto))
    return _tabela_para_segmentos("tabela", linhas)


def carregar_xlsx(path: Path) -> List[Segmento]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    segs: List[Segmento] = []
    try:
        for ws in wb.worksheets:
            linhas = [list(r) for r in ws.iter_rows(values_only=True)]
            segs += _tabela_para_segmentos(f"planilha {ws.title}", linhas)
    finally:
        wb.close()
    return segs


def carregar_json(path: Path) -> List[Segmento]:
    texto = ler_texto(path)
    try:
        texto = json.dumps(json.loads(texto), ensure_ascii=False, indent=1)
    except json.JSONDecodeError:
        pass
    return [Segmento(texto, tipo="codigo")]


def carregar_html(path: Path) -> List[Segmento]:
    html = ler_texto(path)
    try:
        import trafilatura

        txt = trafilatura.extract(html, include_tables=True, favor_recall=True) or ""
    except Exception:  # noqa: BLE001
        txt = ""
    if not txt.strip():
        txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
    return [Segmento(txt)]


CARREGADORES: Dict[str, Callable[[Path], List[Segmento]]] = {
    ".pdf": carregar_pdf,
    ".docx": carregar_docx,
    ".csv": carregar_csv,
    ".tsv": carregar_csv,
    ".xlsx": carregar_xlsx,
    ".xlsm": carregar_xlsx,
    ".json": carregar_json,
    ".html": carregar_html,
    ".htm": carregar_html,
}
for _e in EXT_TEXTO:
    CARREGADORES.setdefault(_e, carregar_texto)
for _e in EXT_CODIGO:
    CARREGADORES.setdefault(_e, carregar_codigo)


def carregar_arquivo(path: Path) -> List[Segmento]:
    fn = CARREGADORES.get(path.suffix.lower())
    if fn is None:
        raise AgenteErro(f"Formato não suportado: {path.suffix}")
    return fn(path)
