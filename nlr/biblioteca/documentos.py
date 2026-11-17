"""Documentos difíceis (v0.5): detecção de página escaneada, OCR opcional e tabelas em markdown.

Tudo aqui é OPCIONAL e degrada com elegância:
* OCR: rapidocr-onnxruntime (pip, sem binário externo; funciona no Windows) -> tesseract (pytesseract + binário)
  -> nenhum (a página é marcada como "escaneada, sem OCR" e o usuário recebe um aviso).
* Imagem da página: pypdfium2 (renderiza) -> imagens embutidas no PDF via pypdf (leve, cobre a maioria dos
  escaneados, que são uma imagem por página).
* Tabelas de PDF: pdfplumber se instalado. DOCX/XLSX/CSV usam só as dependências básicas.
Instale tudo com: pip install "neuron-local-research[documentos]"
"""
from __future__ import annotations

import io
import logging
import shutil
from typing import List, Optional, Sequence

log = logging.getLogger(__name__)

MIN_CHARS_PAGINA = 40  # menos que isso numa página com imagem => provavelmente escaneada


# ------------------------------------------------------------------ tabelas
def _celula(v) -> str:
    s = "" if v is None else str(v)
    return s.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()


def tabela_markdown(linhas: Sequence[Sequence], max_linhas: int = 0) -> str:
    """Converte linhas (a 1ª é o cabeçalho) em tabela markdown. Ignora linhas vazias; iguala o nº de colunas."""
    ls = [[_celula(c) for c in ln] for ln in linhas if ln is not None]
    ls = [ln for ln in ls if any(ln)]
    if not ls:
        return ""
    n = max(len(ln) for ln in ls)
    # remove colunas totalmente vazias
    cheias = [j for j in range(n) if any(j < len(ln) and ln[j] for ln in ls)]
    ls = [[ln[j] if j < len(ln) else "" for j in cheias] for ln in ls]
    cab = [c or f"col{i + 1}" for i, c in enumerate(ls[0])]
    corpo = ls[1:]
    if max_linhas:
        corpo = corpo[:max_linhas]
    out = ["| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)]
    out += ["| " + " | ".join(ln) + " |" for ln in corpo]
    return "\n".join(out)


def tabelas_markdown_em_blocos(linhas: Sequence[Sequence], max_chars: int = 1500) -> List[tuple]:
    """Divide uma tabela grande em blocos markdown (cabeçalho repetido). Devolve [(md, linha_ini, linha_fim)]."""
    ls = [list(ln) for ln in linhas if ln is not None and any(_celula(c) for c in ln)]
    if not ls:
        return []
    cab, corpo = ls[0], ls[1:]
    if not corpo:
        return [(tabela_markdown([cab]), 1, 1)]
    blocos, atual, ini, tam = [], [], 2, 0
    for n, ln in enumerate(corpo, start=2):
        t = sum(len(_celula(c)) + 3 for c in ln)
        if atual and tam + t > max_chars:
            blocos.append((tabela_markdown([cab] + atual), ini, n - 1))
            atual, tam, ini = [], 0, n
        atual.append(ln)
        tam += t
    if atual:
        blocos.append((tabela_markdown([cab] + atual), ini, len(corpo) + 1))
    return blocos


def tabelas_pdf(caminho: str) -> dict:
    """{nº página: [tabela_md, ...]} com pdfplumber; {} se não estiver instalado."""
    try:
        import pdfplumber
    except ImportError:
        return {}
    out: dict = {}
    try:
        with pdfplumber.open(caminho) as pdf:
            for i, pg in enumerate(pdf.pages, start=1):
                for tb in pg.extract_tables() or []:
                    if tb and len(tb) >= 2 and max(len(r) for r in tb) >= 2:
                        md = tabela_markdown(tb)
                        if md:
                            out.setdefault(i, []).append(md)
    except Exception as e:  # noqa: BLE001
        log.warning("Tabelas do PDF não extraídas (%s)", e)
    return out


# ------------------------------------------------------------------ páginas escaneadas
def pagina_parece_escaneada(texto: str, tem_imagem: bool) -> bool:
    util = sum(ch.isalnum() for ch in (texto or ""))
    return util < MIN_CHARS_PAGINA and tem_imagem


def pagina_tem_imagem(page) -> bool:
    try:
        return len(page.images) > 0
    except Exception:  # noqa: BLE001
        try:
            res = page.get("/Resources") or {}
            xo = res.get("/XObject") or {}
            return any(xo[k].get("/Subtype") == "/Image" for k in xo)
        except Exception:  # noqa: BLE001
            return False


def imagens_da_pagina(caminho: str, indice: int, page=None) -> list:
    """Imagens PIL da página (índice 0-based): render com pypdfium2, senão imagens embutidas."""
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(caminho)
        try:
            return [doc[indice].render(scale=2.0).to_pil()]
        finally:
            doc.close()
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        log.debug("pypdfium2 falhou: %s", e)
    imgs = []
    if page is not None:
        try:
            from PIL import Image

            for im in page.images:
                try:
                    imgs.append(Image.open(io.BytesIO(im.data)).convert("RGB"))
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
    return imgs


# ------------------------------------------------------------------ OCR
_MOTOR = {}


def motor_ocr(preferido: str = "auto") -> Optional[str]:
    """Nome do motor de OCR disponível: 'rapidocr' | 'tesseract' | None. preferido='nenhum' desliga."""
    if preferido == "nenhum":
        return None
    if preferido in _MOTOR:
        return _MOTOR[preferido]
    escolha = None
    if preferido in ("auto", "rapidocr"):
        try:
            import rapidocr_onnxruntime  # noqa: F401

            escolha = "rapidocr"
        except Exception:  # noqa: BLE001
            pass
    if escolha is None and preferido in ("auto", "tesseract"):
        try:
            import pytesseract  # noqa: F401

            if shutil.which("tesseract"):
                escolha = "tesseract"
        except ImportError:
            pass
    _MOTOR[preferido] = escolha
    return escolha


_RAPID = None


def ocr_imagem(img, motor: str, idiomas: str = "por+eng") -> str:
    global _RAPID
    if motor == "rapidocr":
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR

        if _RAPID is None:
            _RAPID = RapidOCR()
        res, _ = _RAPID(np.array(img.convert("RGB")))
        if not res:
            return ""
        # agrupa por linha (y) e ordena por x
        caixas = sorted(res, key=lambda r: (round(min(p[1] for p in r[0]) / 12), min(p[0] for p in r[0])))
        linhas, ultima_y, atual = [], None, []
        for r in caixas:
            y = round(min(p[1] for p in r[0]) / 12)
            if ultima_y is not None and y != ultima_y:
                linhas.append(" ".join(atual))
                atual = []
            atual.append(r[1])
            ultima_y = y
        if atual:
            linhas.append(" ".join(atual))
        return "\n".join(linhas)
    if motor == "tesseract":
        import pytesseract

        try:
            return pytesseract.image_to_string(img, lang=idiomas)
        except Exception:  # noqa: BLE001
            return pytesseract.image_to_string(img)
    return ""


def ocr_pagina(caminho: str, indice: int, page=None, motor: str = "auto", idiomas: str = "por+eng") -> str:
    m = motor_ocr(motor)
    if not m:
        return ""
    partes = []
    for img in imagens_da_pagina(caminho, indice, page):
        try:
            partes.append(ocr_imagem(img, m, idiomas))
        except Exception as e:  # noqa: BLE001
            log.warning("OCR falhou na página %d: %s", indice + 1, e)
    return "\n".join(p for p in partes if p.strip())
