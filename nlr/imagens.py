"""Imagens enviadas pela interface/API (v0.7): ficam em dados/imagens/<id>.<ext>, sem sair do seu PC."""
from __future__ import annotations

import base64
import io
import re
import uuid
from pathlib import Path
from typing import Optional

from .erros import AgenteErro
from .ferramentas.visao import EXTENSOES

MAX_MB = 25
_ID = re.compile(r"^[a-f0-9]{12}\.(png|jpg|jpeg|webp|bmp|gif|tif|tiff)$")
MARCADOR = re.compile(r"\[imagem:([a-f0-9]{12}\.[a-z]{3,4})\]")


def pasta(cfg) -> Path:
    p = cfg.dir_dados / "imagens"
    p.mkdir(parents=True, exist_ok=True)
    return p


def caminho(cfg, iid: str) -> Path:
    """Caminho de uma imagem enviada (só ids gerados pelo NLR: nada de ../)."""
    iid = (iid or "").strip().lower()
    if not _ID.match(iid):
        raise AgenteErro(f"imagem inválida: {iid}")
    p = pasta(cfg) / iid
    if not p.is_file():
        raise AgenteErro(f"imagem não encontrada: {iid}")
    return p


def salvar(cfg, nome: str, dados_b64: str) -> dict:
    """Valida (abre com Pillow) e guarda a imagem. Devolve id, dimensões e miniatura."""
    try:
        bruto = base64.b64decode(dados_b64.split(",", 1)[-1])
    except Exception as e:  # noqa: BLE001
        raise AgenteErro("imagem inválida (base64)") from e
    if len(bruto) > MAX_MB * 1024 * 1024:
        raise AgenteErro(f"imagem grande demais (máx. {MAX_MB} MB)")
    ext = Path(nome or "").suffix.lower()
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(bruto))
        im.load()
        fmt = (im.format or "").lower()
    except Exception as e:  # noqa: BLE001
        raise AgenteErro(f"não é uma imagem válida: {nome}") from e
    if ext not in EXTENSOES:
        ext = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif", "bmp": ".bmp", "tiff": ".tif"}.get(fmt, ".png")
    iid = uuid.uuid4().hex[:12] + (".jpg" if ext == ".jpeg" else ext)
    (pasta(cfg) / iid).write_bytes(bruto)
    return {"id": iid, "nome": Path(nome or iid).name, "largura": im.width, "altura": im.height,
            "url": f"/api/imagens/{iid}", "miniatura": miniatura(im)}


def miniatura(im, lado: int = 160) -> str:
    from PIL import Image

    m = im.copy()
    try:
        m.seek(0)
    except Exception:  # noqa: BLE001
        pass
    m = m.convert("RGBA")
    pixel = max(m.size) <= 128
    m.thumbnail((lado, lado), Image.NEAREST if pixel else Image.LANCZOS)
    if pixel and max(m.size) < lado:  # sprite: amplia sem borrar
        f = max(1, lado // max(m.size))
        m = m.resize((m.width * f, m.height * f), Image.NEAREST)
    b = io.BytesIO()
    m.save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def nome_original(texto: str) -> Optional[str]:
    m = MARCADOR.search(texto or "")
    return m.group(1) if m else None
