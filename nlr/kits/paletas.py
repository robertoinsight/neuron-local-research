"""Paletas conhecidas de pixel art + leitura/escrita de .gpl (GIMP/Aseprite), .hex (Lospec) e .pal (JASC)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

RGB = Tuple[int, int, int]


def _h(s: str) -> List[str]:
    return s.split()


PALETAS: Dict[str, List[str]] = {
    "pico-8": _h("000000 1d2b53 7e2553 008751 ab5236 5f574f c2c3c7 fff1e8 ff004d ffa300 ffec27 00e436 29adff 83769c "
                 "ff77a8 ffccaa"),
    "db16": _h("140c1c 442434 30346d 4e4a4e 854c30 346524 d04648 757161 597dce d27d2c 8595a1 6daa2c d2aa99 6dc2ca "
               "dad45e deeed6"),
    "db32": _h("000000 222034 45283c 663931 8f563b df7126 d9a066 eec39a fbf236 99e550 6abe30 37946e 4b692f 524b24 "
               "323c39 3f3f74 306082 5b6ee1 639bff 5fcde4 cbdbfc ffffff 9badb7 847e87 696a6a 595652 76428a ac3232 "
               "d95763 d77bba 8f974a 8a6f30"),
    "endesga-32": _h("be4a2f d77643 ead4aa e4a672 b86f50 733e39 3e2731 a22633 e43b44 f77622 feae34 fee761 63c74d "
                     "3e8948 265c42 193c3e 124e89 0099db 2ce8f5 ffffff c0cbdc 8b9bb4 5a6988 3a4466 262b44 181425 "
                     "ff0044 68386c b55088 f6757a e8b796 c28569"),
    "gameboy": _h("0f380f 306230 8bac0f 9bbc0f"),
    "1bit": _h("000000 ffffff"),
}
APELIDOS = {"pico8": "pico-8", "dawnbringer16": "db16", "dawnbringer32": "db32", "endesga32": "endesga-32",
            "edg32": "endesga-32", "gb": "gameboy", "dmg": "gameboy"}


def hex_para_rgb(h: str) -> RGB:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_para_hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(x) for x in c[:3])


def ler_arquivo_paleta(caminho: Path) -> List[RGB]:
    txt = Path(caminho).read_text(encoding="utf-8", errors="replace").splitlines()
    cores: List[RGB] = []
    if txt and txt[0].strip() == "JASC-PAL":  # .pal
        for ln in txt[3:]:
            p = ln.split()
            if len(p) >= 3:
                cores.append(tuple(int(x) for x in p[:3]))  # type: ignore[arg-type]
        return cores
    for ln in txt:
        s = ln.strip()
        if not s or s.startswith(("#", ";", "GIMP", "Name:", "Columns:")):
            if s.startswith("#") and len(s) in (4, 7) and all(c in "0123456789abcdefABCDEF" for c in s[1:]):
                cores.append(hex_para_rgb(s))
            continue
        p = s.split()
        if len(p) >= 3 and all(x.isdigit() for x in p[:3]):  # .gpl
            cores.append(tuple(int(x) for x in p[:3]))  # type: ignore[arg-type]
        elif len(p[0]) in (6, 3):  # .hex
            try:
                cores.append(hex_para_rgb(p[0]))
            except ValueError:
                pass
    return cores


def obter(nome_ou_caminho: str) -> List[RGB]:
    """Paleta por nome (pico-8, db16, db32, endesga-32, gameboy, 1bit), arquivo (.gpl/.hex/.pal) ou lista '#aabbcc,#..'."""
    n = (nome_ou_caminho or "").strip()
    chave = APELIDOS.get(n.lower().replace(" ", ""), n.lower())
    if chave in PALETAS:
        return [hex_para_rgb(h) for h in PALETAS[chave]]
    if "," in n or (n.startswith("#") and not Path(n).exists()):
        return [hex_para_rgb(x) for x in n.replace(";", ",").split(",") if x.strip()]
    p = Path(n).expanduser()
    if p.exists():
        return ler_arquivo_paleta(p)
    raise ValueError(f"Paleta desconhecida: {n}. Use: {', '.join(PALETAS)} ou um arquivo .gpl/.hex/.pal")


def salvar_paleta(cores: List[RGB], caminho: Path, nome: str = "NLR") -> Path:
    caminho = Path(caminho)
    if caminho.suffix.lower() == ".hex":
        caminho.write_text("\n".join(rgb_para_hex(c)[1:] for c in cores) + "\n", encoding="utf-8")
    elif caminho.suffix.lower() == ".pal":
        caminho.write_text("JASC-PAL\n0100\n%d\n" % len(cores) + "\n".join("%d %d %d" % tuple(c[:3]) for c in cores) + "\n",
                           encoding="utf-8")
    else:
        linhas = ["GIMP Palette", f"Name: {nome}", "Columns: 8", "#"]
        linhas += ["%3d %3d %3d\t%s" % (c[0], c[1], c[2], rgb_para_hex(c)) for c in cores]
        caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho
