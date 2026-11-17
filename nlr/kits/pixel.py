"""Kit Pixel Art (v0.6) — só Pillow (+numpy, já dependência). Aseprite CLI é usado quando instalado.

Funções puras (recebem/devolvem PIL.Image) para serem usadas pela CLI (`nlr pixel ...`), pela API/UI e pelas
ferramentas do agente. Nada aqui usa o modelo de linguagem: funciona igual com modelos de qualquer tamanho.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from collections import Counter, deque
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from . import paletas as P

EXT_ASE = (".ase", ".aseprite")


# ------------------------------------------------------------------ básicos
def abrir(caminho) -> Image.Image:
    p = Path(caminho)
    if p.suffix.lower() in EXT_ASE:
        return abrir_ase(p)
    im = Image.open(p)
    im.load()
    return im.convert("RGBA")


def redimensionar(im: Image.Image, largura: int = 0, altura: int = 0, fator: float = 0) -> Image.Image:
    """Nearest-neighbor (sem borrar). Ex.: 128x128 -> 32x32 com largura=32 (altura proporcional) ou fator=0.25."""
    w, h = im.size
    if fator:
        largura, altura = max(1, round(w * fator)), max(1, round(h * fator))
    elif largura and not altura:
        altura = max(1, round(h * largura / w))
    elif altura and not largura:
        largura = max(1, round(w * altura / h))
    if not (largura and altura):
        raise ValueError("Informe largura/altura ou fator.")
    return im.resize((int(largura), int(altura)), Image.NEAREST)


def upscale(im: Image.Image, fator: int = 4) -> Image.Image:
    """Ampliação inteira (cada pixel vira um bloco fator x fator)."""
    fator = int(fator)
    if fator < 1:
        raise ValueError("fator deve ser inteiro >= 1")
    return im.resize((im.width * fator, im.height * fator), Image.NEAREST)


def _arr(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("RGBA")).copy()


# ------------------------------------------------------------------ paletas
def extrair_paleta(im: Image.Image, maximo: int = 64) -> List[Tuple[int, int, int]]:
    """Cores usadas (ignora pixels transparentes), da mais para a menos frequente."""
    a = _arr(im)
    vis = a[a[:, :, 3] > 0][:, :3]
    cont = Counter(map(tuple, vis.tolist()))
    return [tuple(c) for c, _ in cont.most_common(maximo)]  # type: ignore[misc]


def _lab(rgb) -> np.ndarray:
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def aplicar_paleta(im: Image.Image, paleta, dither: bool = False) -> Image.Image:
    """Troca cada pixel pela cor mais próxima da paleta (distância perceptual simples). Preserva a transparência."""
    cores = P.obter(paleta) if isinstance(paleta, str) else [tuple(c[:3]) for c in paleta]
    if not cores:
        raise ValueError("paleta vazia")
    a = _arr(im)
    alfa = a[:, :, 3]
    if dither:
        pal = Image.new("P", (1, 1))
        flat = [v for c in cores for v in c]
        pal.putpalette(flat + [0] * (768 - len(flat)))
        q = im.convert("RGB").quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG).convert("RGBA")
        out = np.asarray(q).copy()
        out[:, :, 3] = alfa
        return Image.fromarray(out, "RGBA")
    rgb = a[:, :, :3].reshape(-1, 3)
    pc = np.array(cores, dtype=np.int32)
    # distância em CIELAB (perceptual); cores únicas primeiro para ficar rápido em imagens grandes
    unicas, inv = np.unique(rgb, axis=0, return_inverse=True)
    lu, lp = _lab(unicas), _lab(pc)
    idx_u = np.empty(len(unicas), dtype=np.int32)
    for i in range(0, len(unicas), 16384):
        d = ((lu[i:i + 16384, None, :] - lp[None, :, :]) ** 2).sum(axis=2)
        idx_u[i:i + 16384] = d.argmin(axis=1)
    idx = idx_u[inv.reshape(-1)]
    novo = pc[idx].reshape(a.shape[0], a.shape[1], 3).astype(np.uint8)
    return Image.fromarray(np.dstack([novo, alfa]), "RGBA")


def reduzir_paleta(im: Image.Image, cores: int = 16, dither: bool = False) -> Image.Image:
    """Reduz para N cores (median cut) preservando a transparência."""
    a = _arr(im)
    q = Image.fromarray(a[:, :, :3], "RGB").quantize(colors=max(2, int(cores)), method=Image.Quantize.MEDIANCUT,
                                                     dither=Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE)
    out = np.asarray(q.convert("RGB"))
    return Image.fromarray(np.dstack([out, a[:, :, 3]]), "RGBA")


# ------------------------------------------------------------------ fundo
def remover_fundo(im: Image.Image, cor: Optional[str] = None, tolerancia: int = 0, contiguo: bool = True) -> Image.Image:
    """Deixa o fundo transparente. Cor padrão = pixel do canto superior esquerdo. contiguo=True só apaga a região
    ligada às bordas (não fura o sprite quando a cor se repete dentro dele)."""
    a = _arr(im)
    h, w = a.shape[:2]
    alvo = np.array(P.hex_para_rgb(cor) if cor else a[0, 0, :3], dtype=np.int32)
    perto = (np.abs(a[:, :, :3].astype(np.int32) - alvo).max(axis=2) <= int(tolerancia)) & (a[:, :, 3] > 0)
    if not contiguo:
        a[perto, 3] = 0
        return Image.fromarray(a, "RGBA")
    marc = np.zeros((h, w), bool)
    fila = deque([(y, x) for x in range(w) for y in (0, h - 1)] + [(y, x) for y in range(h) for x in (0, w - 1)])
    while fila:
        y, x = fila.popleft()
        if not (0 <= y < h and 0 <= x < w) or marc[y, x] or not perto[y, x]:
            continue
        marc[y, x] = True
        fila.extend(((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)))
    a[marc, 3] = 0
    return Image.fromarray(a, "RGBA")


# ------------------------------------------------------------------ spritesheets
def fatiar(im: Image.Image, largura: int, altura: int, margem: int = 0, espaco: int = 0,
           pular_vazios: bool = True) -> List[Image.Image]:
    """Corta uma spritesheet em quadros largura x altura (linha a linha)."""
    quadros = []
    y = margem
    while y + altura <= im.height:
        x = margem
        while x + largura <= im.width:
            q = im.crop((x, y, x + largura, y + altura))
            if not (pular_vazios and q.getbbox() is None and q.mode == "RGBA" and q.getchannel("A").getbbox() is None):
                quadros.append(q)
            x += largura + espaco
        y += altura + espaco
    return quadros


def montar(quadros: Sequence[Image.Image], colunas: int = 0, espaco: int = 0,
           nomes: Optional[Sequence[str]] = None, duracao_ms: int = 100) -> Tuple[Image.Image, dict]:
    """Monta spritesheet em grade + JSON no formato do Aseprite (frames/meta), lido por Godot/Unity/Phaser."""
    if not quadros:
        raise ValueError("nenhum quadro")
    w = max(q.width for q in quadros)
    h = max(q.height for q in quadros)
    colunas = colunas or math.ceil(math.sqrt(len(quadros)))
    linhas = math.ceil(len(quadros) / colunas)
    folha = Image.new("RGBA", (colunas * w + (colunas - 1) * espaco, linhas * h + (linhas - 1) * espaco), (0, 0, 0, 0))
    frames = {}
    for i, q in enumerate(quadros):
        x, y = (i % colunas) * (w + espaco), (i // colunas) * (h + espaco)
        folha.paste(q.convert("RGBA"), (x, y))
        nome = (nomes[i] if nomes and i < len(nomes) else f"quadro {i}")
        frames[nome] = {"frame": {"x": x, "y": y, "w": q.width, "h": q.height}, "rotated": False, "trimmed": False,
                        "spriteSourceSize": {"x": 0, "y": 0, "w": q.width, "h": q.height},
                        "sourceSize": {"w": q.width, "h": q.height}, "duration": duracao_ms}
    meta = {"frames": frames, "meta": {"app": "Neuron Local Research", "version": "0.6", "image": "",
                                       "format": "RGBA8888", "size": {"w": folha.width, "h": folha.height}, "scale": "1"}}
    return folha, meta


# ------------------------------------------------------------------ preview e GIF
def xadrez(w: int, h: int, celula: int = 8, c1=(200, 200, 200, 255), c2=(150, 150, 150, 255)) -> Image.Image:
    a = np.zeros((h, w, 4), np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    m = ((yy // celula + xx // celula) % 2).astype(bool)
    a[~m], a[m] = c1, c2
    return Image.fromarray(a, "RGBA")


def preview(im: Image.Image, fator: int = 0, fundo: str = "xadrez", tamanho_alvo: int = 256) -> Image.Image:
    """Ampliação inteira para visualizar (fator automático até ~tamanho_alvo px) sobre fundo xadrez ou cor."""
    fator = fator or max(1, tamanho_alvo // max(im.width, im.height))
    g = upscale(im.convert("RGBA"), fator)
    base = xadrez(g.width, g.height, max(4, fator)) if fundo == "xadrez" else Image.new("RGBA", g.size, P.hex_para_rgb(fundo) + (255,))
    return Image.alpha_composite(base, g)


def gif(quadros: Sequence[Image.Image], destino, duracao_ms: int = 100, fator: int = 1, loop: int = 0) -> Path:
    """GIF animado com transparência (pixels alfa 0 viram transparentes)."""
    destino = Path(destino)
    conv = []
    for q in quadros:
        q = upscale(q.convert("RGBA"), fator) if fator > 1 else q.convert("RGBA")
        alfa = q.getchannel("A")
        p = q.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        mascara = Image.eval(alfa, lambda v: 255 if v < 128 else 0)
        p.paste(255, mascara)
        conv.append(p)
    conv[0].save(destino, save_all=True, append_images=conv[1:], duration=duracao_ms, loop=loop, transparency=255,
                 disposal=2, optimize=False)
    return destino


# ------------------------------------------------------------------ Aseprite (CLI)
def caminhos_aseprite() -> List[Path]:
    """Lugares comuns do executável (Windows: instalador, Steam, itch; macOS; Linux)."""
    c: List[Path] = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(var)
        if base:
            c += [Path(base) / "Aseprite" / "Aseprite.exe", Path(base) / "Steam" / "steamapps" / "common" / "Aseprite" / "Aseprite.exe"]
    for var in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(var)
        if base:
            c += [Path(base) / "Programs" / "Aseprite" / "Aseprite.exe", Path(base) / "itch" / "apps" / "aseprite" / "Aseprite.exe"]
    c += [Path("C:/Program Files/Aseprite/Aseprite.exe"), Path("C:/Program Files (x86)/Steam/steamapps/common/Aseprite/Aseprite.exe"),
          Path("/Applications/Aseprite.app/Contents/MacOS/aseprite"),
          Path.home() / "Library/Application Support/Steam/steamapps/common/Aseprite/Aseprite.app/Contents/MacOS/aseprite",
          Path.home() / ".steam/steam/steamapps/common/Aseprite/aseprite", Path("/usr/bin/aseprite"), Path("/usr/local/bin/aseprite")]
    return c


def detectar_aseprite(configurado: str = "") -> Optional[str]:
    """Executável do Aseprite: config kits.pixel.aseprite > variável ASEPRITE > PATH > locais comuns."""
    for cand in (configurado, os.environ.get("ASEPRITE", "")):
        if cand and Path(cand).expanduser().exists():
            return str(Path(cand).expanduser())
    for nome in ("aseprite", "Aseprite", "aseprite.exe"):
        w = shutil.which(nome)
        if w:
            return w
    for p in caminhos_aseprite():
        if p.exists():
            return str(p)
    return None


class Aseprite:
    """Wrapper do modo --batch. Sem Aseprite, os métodos de exportação usam o leitor .ase embutido (fallback)."""

    def __init__(self, executavel: Optional[str] = None, timeout: int = 120):
        self.exe = executavel if executavel is not None else detectar_aseprite()
        self.timeout = timeout

    @property
    def disponivel(self) -> bool:
        return bool(self.exe)

    def _rodar(self, args: List[str]) -> str:
        if not self.exe:
            raise RuntimeError("Aseprite não encontrado (configure kits.pixel.aseprite ou a variável ASEPRITE).")
        r = subprocess.run([self.exe, "--batch"] + args, capture_output=True, text=True, timeout=self.timeout)
        if r.returncode != 0:
            raise RuntimeError(f"Aseprite falhou ({r.returncode}): {(r.stderr or r.stdout)[-800:]}")
        return (r.stdout or "").strip()

    def versao(self) -> str:
        return self._rodar(["--version"]) if self.exe else ""

    def exportar_png(self, arquivo, destino, escala: int = 1, camada: str = "", tag: str = "") -> List[Path]:
        """Exporta quadros em PNG. Com vários quadros, o destino vira 'nome{frame}.png' (padrão do Aseprite)."""
        arquivo, destino = Path(arquivo), Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        if self.exe:
            args = []
            if camada:
                args += ["--layer", camada]
            if tag:
                args += ["--tag", tag]
            args += [str(arquivo)]
            if escala != 1:
                args += ["--scale", str(escala)]
            args += ["--save-as", str(destino.with_name(destino.stem + "{frame}" + destino.suffix))]
            self._rodar(args)
            return sorted(destino.parent.glob(destino.stem + "*" + destino.suffix))
        quadros = ler_ase(arquivo)["quadros"]
        saidas = []
        for i, q in enumerate(quadros):
            alvo = destino if len(quadros) == 1 else destino.with_name(f"{destino.stem}{i}{destino.suffix}")
            (upscale(q, escala) if escala > 1 else q).save(alvo)
            saidas.append(alvo)
        return saidas

    def exportar_sheet(self, arquivo, destino_png, destino_json=None, tipo: str = "horizontal", escala: int = 1,
                       tag: str = "") -> Tuple[Path, Optional[Path]]:
        """Spritesheet + JSON (formato hash do Aseprite). tipo: horizontal | vertical | rows | columns | packed."""
        arquivo, destino_png = Path(arquivo), Path(destino_png)
        destino_json = Path(destino_json) if destino_json else destino_png.with_suffix(".json")
        destino_png.parent.mkdir(parents=True, exist_ok=True)
        if self.exe:
            args = [str(arquivo)]
            if tag:
                args += ["--tag", tag]
            if escala != 1:
                args += ["--scale", str(escala)]
            args += ["--sheet", str(destino_png), "--sheet-type", tipo, "--data", str(destino_json),
                     "--format", "json-hash", "--list-tags"]
            self._rodar(args)
            return destino_png, destino_json
        d = ler_ase(arquivo)
        qs = [upscale(q, escala) if escala > 1 else q for q in d["quadros"]]
        col = {"horizontal": len(qs), "vertical": 1}.get(tipo, 0)
        folha, meta = montar(qs, colunas=col, nomes=[f"{arquivo.stem} {i}.aseprite" for i in range(len(qs))],
                             duracao_ms=100)
        for i, nome in enumerate(meta["frames"]):
            meta["frames"][nome]["duration"] = d["duracoes"][i] if i < len(d["duracoes"]) else 100
        meta["meta"]["image"] = destino_png.name
        meta["meta"]["frameTags"] = d["tags"]
        folha.save(destino_png)
        destino_json.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return destino_png, destino_json

    def rodar_script(self, script_lua, parametros: Optional[Dict[str, str]] = None, arquivo=None) -> str:
        """Roda um script Lua (API do Aseprite) em modo batch. parametros viram --script-param chave=valor."""
        args = []
        if arquivo:
            args.append(str(arquivo))
        for k, v in (parametros or {}).items():
            args += ["--script-param", f"{k}={v}"]
        args += ["--script", str(script_lua)]
        return self._rodar(args)


# scripts Lua prontos (salvos sob demanda em uma pasta do usuário)
SCRIPTS_LUA = {
    "aplicar_paleta.lua": '''-- Aplica uma paleta (.gpl/.pal/.ase) ao sprite e salva. Uso:
-- aseprite --batch sprite.aseprite --script-param paleta=db32.gpl --script-param saida=out.aseprite --script aplicar_paleta.lua
local spr = app.activeSprite
if not spr then return print("sem sprite") end
local pal = Palette{ fromFile = app.params["paleta"] }
spr:setPalette(pal)
app.command.ChangePixelFormat{ format = "indexed", dithering = app.params["dither"] or "none" }
spr:saveCopyAs(app.params["saida"] or spr.filename)
print("ok")
''',
    "exportar_camadas.lua": '''-- Exporta cada camada visível em PNG separado: --script-param pasta=saida
local spr = app.activeSprite
if not spr then return print("sem sprite") end
local pasta = app.params["pasta"] or "."
for _, layer in ipairs(spr.layers) do
  if layer.isVisible and not layer.isGroup then
    for _, l in ipairs(spr.layers) do l.isVisible = (l == layer) end
    spr:saveCopyAs(pasta .. "/" .. layer.name .. ".png")
  end
end
print("ok")
''',
    "redimensionar.lua": '''-- Redimensiona (nearest) para LxA: --script-param largura=32 --script-param altura=32 --script-param saida=out.aseprite
local spr = app.activeSprite
if not spr then return print("sem sprite") end
app.command.SpriteSize{ width = tonumber(app.params["largura"]), height = tonumber(app.params["altura"]), method = "nearest" }
spr:saveCopyAs(app.params["saida"] or spr.filename)
print("ok")
''',
}


def salvar_scripts_lua(pasta) -> List[Path]:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    out = []
    for nome, src in SCRIPTS_LUA.items():
        p = pasta / nome
        p.write_text(src, encoding="utf-8")
        out.append(p)
    return out


# ------------------------------------------------------------------ leitor .ase/.aseprite (fallback sem Aseprite)
def ler_ase(caminho) -> dict:
    """Leitor mínimo do formato .aseprite (spec oficial): RGBA/grayscale/indexado, cels raw/linked/compressed,
    camadas normais visíveis com opacidade, tags e durações. Não aplica blend modes além de 'normal'."""
    import struct
    import zlib

    dados = Path(caminho).read_bytes()
    if len(dados) < 128 or struct.unpack_from("<H", dados, 4)[0] != 0xA5E0:
        raise ValueError("arquivo .aseprite inválido")
    n_frames, w, h, prof = struct.unpack_from("<HHHH", dados, 6)
    flags = struct.unpack_from("<I", dados, 14)[0]
    transp_idx = dados[28]
    pos = 128
    camadas: List[dict] = []
    paleta: List[Tuple[int, int, int, int]] = [(0, 0, 0, 255)] * 256
    quadros, duracoes, tags = [], [], []
    cels_por_frame: List[Dict[int, Image.Image]] = []
    pos_cel: List[Dict[int, Tuple[int, int, int]]] = []
    for fi in range(n_frames):
        tam_frame, magico, chunks_antigos, dur = struct.unpack_from("<IHHH", dados, pos)
        chunks_novos = struct.unpack_from("<I", dados, pos + 12)[0]
        n_chunks = chunks_novos or chunks_antigos
        duracoes.append(dur)
        cp = pos + 16
        cels: Dict[int, Image.Image] = {}
        posicoes: Dict[int, Tuple[int, int, int]] = {}
        for _ in range(n_chunks):
            tam, tipo = struct.unpack_from("<IH", dados, cp)
            corpo = dados[cp + 6: cp + tam]
            if tipo == 0x2004:  # layer
                fl, tl, _, _, _, blend, opac = struct.unpack_from("<HHHHHHB", corpo, 0)
                camadas.append({"visivel": bool(fl & 1), "tipo": tl, "opacidade": opac if flags & 1 else 255})
            elif tipo == 0x2019:  # palette
                total, ini, fim = struct.unpack_from("<III", corpo, 0)
                q = 20
                for i in range(ini, fim + 1):
                    ef = struct.unpack_from("<H", corpo, q)[0]
                    r, g, b, a = corpo[q + 2: q + 6]
                    paleta[i] = (r, g, b, a)
                    q += 6
                    if ef & 1:
                        q += 2 + struct.unpack_from("<H", corpo, q)[0]
            elif tipo == 0x2018:  # tags
                nt = struct.unpack_from("<H", corpo, 0)[0]
                q = 10
                for _t in range(nt):
                    de, ate, direc = struct.unpack_from("<HHB", corpo, q)
                    q += 17
                    ln = struct.unpack_from("<H", corpo, q)[0]
                    nome = corpo[q + 2: q + 2 + ln].decode("utf-8", "replace")
                    q += 2 + ln
                    tags.append({"name": nome, "from": de, "to": ate,
                                 "direction": ["forward", "reverse", "pingpong", "pingpong_reverse"][min(direc, 3)]})
            elif tipo == 0x2005:  # cel
                li, x, y, opac, tc = struct.unpack_from("<HhhBH", corpo, 0)
                q = 16
                if tc == 1:  # linked
                    origem = struct.unpack_from("<H", corpo, q)[0]
                    if origem < len(cels_por_frame) and li in cels_por_frame[origem]:
                        cels[li] = cels_por_frame[origem][li]
                        posicoes[li] = pos_cel[origem][li]
                elif tc in (0, 2):
                    cw, ch = struct.unpack_from("<HH", corpo, q)
                    px = corpo[q + 4:]
                    if tc == 2:
                        px = zlib.decompress(px)
                    if prof == 32:
                        img = Image.frombytes("RGBA", (cw, ch), bytes(px[: cw * ch * 4]))
                    elif prof == 16:
                        ga = np.frombuffer(px[: cw * ch * 2], np.uint8).reshape(ch, cw, 2)
                        img = Image.fromarray(np.dstack([ga[:, :, 0]] * 3 + [ga[:, :, 1]]), "RGBA")
                    else:
                        ix = np.frombuffer(px[: cw * ch], np.uint8).reshape(ch, cw)
                        lut = np.array(paleta, np.uint8)
                        rgba = lut[ix].copy()
                        rgba[ix == transp_idx, 3] = 0
                        img = Image.fromarray(rgba, "RGBA")
                    cels[li] = img
                    posicoes[li] = (x, y, opac)
            cp += tam
        cels_por_frame.append(cels)
        pos_cel.append(posicoes)
        base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for li in sorted(cels):
            cam = camadas[li] if li < len(camadas) else {"visivel": True, "opacidade": 255, "tipo": 0}
            if not cam["visivel"] or cam["tipo"] == 1:
                continue
            x, y, opac = posicoes[li]
            img = cels[li]
            fator = (opac / 255) * (cam["opacidade"] / 255)
            if fator < 1:
                a = np.asarray(img).copy()
                a[:, :, 3] = (a[:, :, 3] * fator).astype(np.uint8)
                img = Image.fromarray(a, "RGBA")
            camada = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            camada.paste(img, (x, y))
            base = Image.alpha_composite(base, camada)
        quadros.append(base)
        pos += tam_frame
    return {"largura": w, "altura": h, "profundidade": prof, "quadros": quadros, "duracoes": duracoes, "tags": tags,
            "camadas": len(camadas)}


def abrir_ase(caminho) -> Image.Image:
    return ler_ase(caminho)["quadros"][0]


def escrever_ase_rgba(quadros: Sequence[Image.Image], destino, duracao_ms: int = 100) -> Path:
    """Gera um .aseprite RGBA simples (1 camada, cels comprimidos). Útil para testes e para levar ao Aseprite."""
    import struct
    import zlib

    w, h = quadros[0].size
    camada = struct.pack("<HHHHHHB3xH", 1 | 2, 0, 0, 0, 0, 0, 255, 6) + b"Camada"
    corpo_frames = b""
    for i, q in enumerate(quadros):
        chunks = []
        if i == 0:
            chunks.append(struct.pack("<IH", 6 + len(camada), 0x2004) + camada)
        px = zlib.compress(q.convert("RGBA").tobytes())
        cel = struct.pack("<HhhBH7x", 0, 0, 0, 255, 2) + struct.pack("<HH", w, h) + px
        chunks.append(struct.pack("<IH", 6 + len(cel), 0x2005) + cel)
        corpo = b"".join(chunks)
        corpo_frames += struct.pack("<IHHH2xI", 16 + len(corpo), 0xF1FA, len(chunks), duracao_ms, len(chunks)) + corpo
    cab = struct.pack("<IHHHHHIHIIBB3xHBBhhHH", 128 + len(corpo_frames), 0xA5E0, len(quadros), w, h, 32, 1, 100, 0, 0,
                      0, 0, 0, 1, 1, 0, 0, 0, 0)
    cab = cab + b"\0" * (128 - len(cab))
    Path(destino).write_bytes(cab + corpo_frames)
    return Path(destino)


# ------------------------------------------------------------------ referências na web
def consultas_referencia(tema: str, idioma: str = "pt") -> List[str]:
    base = tema.strip()
    if idioma == "en":
        return [f"{base} pixel art tutorial", f"{base} pixel art reference", f"{base} aseprite tutorial"]
    return [f"{base} pixel art tutorial", f"{base} pixel art referência", f"{base} aseprite tutorial"]
