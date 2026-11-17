"""Visão: análise minuciosa de imagens com um modelo de visão local e pesquisa na web a partir de imagens.

Funciona com qualquer modelo multimodal servido por LM Studio/Ollama/llama.cpp (API compatível com OpenAI):
Qwen2.5-VL / Qwen3-VL, Gemma 3/4, LLaVA, MiniCPM-V... Configure `modelo.modelo_visao` no config.yaml
(vazio = usa o modelo_chat se ele tiver visão; senão, um modelo de visão já carregado no servidor).

Por que "minuciosa": modelos de visão locais reduzem a imagem internamente e perdem detalhes pequenos.
No modo minucioso, a imagem vai inteira (visão geral) e também recortada em quadrantes ampliados, para o modelo
enxergar texto miúdo, objetos pequenos e artefatos. Pixel art é ampliada sem suavizar (nearest-neighbor).

Pesquisa pela imagem: o modelo descreve a imagem e propõe buscas (texto visível, marcas, modelos, lugares...);
o NLR pesquisa na web e responde citando as fontes. A foto NÃO sai do seu PC. Busca reversa de verdade
(Google Lens via SerpApi) é opcional, desligada por padrão e exige consentimento explícito no config.
Nunca identifica pessoas pelo rosto.

Este módulo tem duas camadas:
  * funções de serviço (estado_visao, analisar, pesquisar) usadas pela CLI, API e interface;
  * ferramentas do agente (analisar_imagem, pesquisar_por_imagem), que passam pela política de leitura.
"""
from __future__ import annotations

import base64
import io
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, Field

from ..erros import AgenteErro
from ..fontes import Fonte
from ..i18n import t
from ..llm.texto import extrair_json
from .registro import ferramenta

EXTENSOES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
MODOS = ("minucioso", "geral", "texto", "pixel")
LADO_PIXEL_ART = 768     # pixel art pequena é ampliada até ~isso, sem suavizar
LIMIAR_QUADRANTES = 1024  # imagens maiores que isso ganham recortes no modo minucioso
LADO_RECORTE = 1024       # lado máximo de cada recorte ampliado

PROMPTS = {
    "geral": "Descreva a imagem com precisão: o que aparece, onde, cores, texto visível e contexto provável.",
    "minucioso": (
        "Faça uma análise MINUCIOSA da imagem. A primeira imagem é a visão geral; as seguintes (se houver) são "
        "recortes ampliados dos quadrantes (superior-esquerdo, superior-direito, inferior-esquerdo, inferior-direito). "
        "Responda em seções:\n"
        "1. Visão geral (tipo de imagem: foto, captura de tela, desenho, pixel art, diagrama, documento...)\n"
        "2. Elementos, um por linha, com posição (ex.: 'canto superior esquerdo')\n"
        "3. Todo texto visível, transcrito exatamente (marque [ilegível] quando não der para ler)\n"
        "4. Cores, iluminação, composição e estilo\n"
        "5. Detalhes pequenos e anomalias (artefatos, sinais de edição/IA, erros, partes cortadas)\n"
        "6. Contexto provável (lugar, época, finalidade), separando o que é VISTO do que é INFERIDO\n"
        "7. Incertezas: o que você não consegue afirmar com segurança\n"
        "Não identifique pessoas reais pelo rosto; descreva apenas aparência e ações."),
    "texto": ("Transcreva TODO o texto da imagem exatamente como aparece, preservando linhas, tabelas e ordem de "
              "leitura. Marque [ilegível] onde não for possível ler. Não resuma e não invente texto."),
    "pixel": (
        "Você é um revisor de pixel art. Analise o sprite/cena: 1) leitura da silhueta em tamanho real; "
        "2) paleta (quantas cores, contraste, rampas de cor); 3) contorno (pixels órfãos, 'jaggies', espessura "
        "inconsistente); 4) luz e sombra (direção coerente?); 5) anti-aliasing e banding; 6) proporções e "
        "consistência entre quadros, se for spritesheet. Termine com até 5 correções concretas, citando a região. "
        "Lembre: em pixel art o serrilhado é intencional; NÃO recomende 'adicionar anti-aliasing automático', "
        "'suavizar' nem 'reduzir a pixelação'. Use as MEDIDAS OBJETIVAS abaixo (calculadas pelo NLR, confiáveis)."),
}
# Modo minucioso em etapas (melhor para modelos pequenos): cada recorte ampliado vira notas curtas e,
# no fim, o modelo olha a imagem inteira junto com as notas e escreve a análise completa.
REGIOES = ("superior esquerdo", "superior direito", "inferior esquerdo", "inferior direito")
PROMPT_RECORTE = (
    "Esta é uma AMPLIAÇÃO do quadrante {regiao} de uma imagem maior. Liste, em tópicos curtos, só o que você "
    "REALMENTE vê aqui: objetos, pessoas (sem identificar quem são), texto legível transcrito exatamente, detalhes "
    "pequenos e defeitos. Se não houver nada relevante, responda apenas: (nada relevante). Não invente.")
PROMPT_FINAL_MINUCIOSO = (
    "Abaixo estão NOTAS feitas olhando ampliações de cada quadrante desta imagem. Use a imagem e as notas para "
    "escrever a análise final. Inclua nas seções os detalhes das notas que forem coerentes com a imagem; "
    "ignore o que contradiz a imagem.\n\nNOTAS DOS QUADRANTES:\n{notas}\n\n")
PROMPT_VARIAS = ("Você recebeu {n} imagens, na ordem (Imagem 1, Imagem 2...). Descreva cada uma e depois compare: "
                 "semelhanças, diferenças e o que muda entre elas.")


# ====================================================================== modelo de visão
@dataclass
class EstadoVisao:
    modelo: str = ""
    origem: str = ""  # modelo_visao | modelo_chat | auto
    tem_visao: Optional[bool] = None  # None = o servidor não informa
    carregado: Optional[bool] = None
    backend: str = ""
    avisos: List[str] = field(default_factory=list)
    erro: str = ""
    modelos_visao: List[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.erro

    def dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d


def _achar(modelos, nome: str):
    alvo = (nome or "").lower().removesuffix(":latest")
    for m in modelos:
        if m.id == nome:
            return m
    for m in modelos:
        if m.id.lower().removesuffix(":latest") == alvo:
            return m
    return None


def estado_visao(llm, cfg) -> EstadoVisao:
    """Descobre qual modelo vai analisar as imagens e se ele tem visão / está carregado (sem gerar texto)."""
    from ..nucleo import descoberta

    ep = llm.principal
    est = EstadoVisao(backend=ep.backend)
    try:
        llm._resolver_modelos(ep)
        try:
            modelos = descoberta.listar(ep.backend, ep.base_url, ep.api_key)
            llm.modelos_servidor = modelos
        except Exception:  # noqa: BLE001
            modelos = list(llm.modelos_servidor or [])
    except AgenteErro as e:
        est.modelo = cfg.modelo.modelo_visao or cfg.modelo.modelo_chat
        est.erro = str(e)
        return est
    visoes = [m for m in modelos if m.visao]
    est.modelos_visao = [{"id": m.id, "carregado": m.carregado, "parametros_b": m.parametros_b} for m in visoes]
    lista = ", ".join(m.id for m in visoes[:8]) or "(nenhum)"
    if cfg.modelo.modelo_visao.strip():
        est.modelo, est.origem = cfg.modelo.modelo_visao.strip(), "modelo_visao"
        info = _achar(modelos, est.modelo)
        if info is None:
            if modelos and ep.backend in ("lmstudio", "ollama", "llamacpp"):
                est.erro = t("visao.nao_encontrado", modelo=est.modelo, lista=lista)
            return est
    else:
        est.modelo, est.origem = ep.modelo_chat, "modelo_chat"
        info = _achar(modelos, est.modelo)
        if info is not None and info.visao_conhecida and not info.visao:
            carregados = [m for m in visoes if m.carregado]
            # LM Studio carrega sob demanda (JIT); nos outros só vale um modelo já carregado/servido
            escolha = carregados[0] if carregados else (visoes[0] if visoes and ep.backend in ("lmstudio", "ollama") else None)
            if escolha is None:
                est.tem_visao = False
                est.erro = t("visao.nenhum", modelo=est.modelo)
                return est
            info, est.modelo, est.origem = escolha, escolha.id, "auto"
            est.avisos.append(t("visao.auto", modelo=escolha.id))
    if info is None:
        est.avisos.append(t("visao.desconhecido", modelo=est.modelo))
        return est
    est.modelo = info.id
    est.tem_visao = info.visao if info.visao_conhecida else None
    est.carregado = info.carregado if ep.backend in ("lmstudio", "ollama") else (True if ep.backend == "llamacpp" else None)
    if est.tem_visao is False:
        est.erro = t("visao.sem_visao", modelo=info.id)
    elif est.tem_visao is None:
        est.avisos.append(t("visao.desconhecido", modelo=info.id))
    if not est.erro and est.carregado is False and ep.backend == "lmstudio":
        est.avisos.append(t("visao.nao_carregado", modelo=info.id))
    return est


# ====================================================================== preparo das imagens
def _pil():
    try:
        from PIL import Image, ImageOps  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise AgenteErro("A análise de imagens precisa do Pillow (pip install pillow).") from e


def abrir_imagem(p: Path):
    """Abre a imagem (corrige a rotação do celular) e lê alguns campos EXIF. Devolve (imagem, exif)."""
    _pil()
    from PIL import Image, ImageOps

    if not p.exists():
        raise AgenteErro(f"imagem não encontrada: {p.name}")
    if p.suffix.lower() not in EXTENSOES:
        raise AgenteErro(f"formato não suportado ({p.suffix}). Use: {', '.join(sorted(EXTENSOES))}")
    try:
        img = Image.open(p)
        img.load()
    except Exception as e:  # noqa: BLE001
        raise AgenteErro(f"não consegui abrir a imagem {p.name}: {e}") from e
    exif = _exif(img)
    try:
        img.seek(0)
    except Exception:  # noqa: BLE001
        pass
    img = ImageOps.exif_transpose(img)
    return img, exif


def _exif(img) -> dict:
    out = {}
    try:
        from PIL.ExifTags import TAGS

        dados = img.getexif() or {}
        for k, v in dados.items():
            nome = TAGS.get(k, str(k))
            if nome in ("Make", "Model", "DateTime", "Software", "Artist"):
                out[nome] = str(v)[:80]
        if dados.get(0x8825):
            out["GPS"] = "presente (coordenadas na imagem)"
    except Exception:  # noqa: BLE001
        pass
    return out


def eh_pixel_art(img) -> bool:
    if max(img.size) > 320:
        return False
    try:
        cores = img.convert("RGBA").getcolors(maxcolors=256)
    except Exception:  # noqa: BLE001
        return False
    return cores is not None


def medidas_pixel_art(img) -> str:
    """Números objetivos que um modelo pequeno não consegue contar sozinho (cores, pixels órfãos, transparência)."""
    im = img.convert("RGBA")
    w, h = im.size
    px = im.load()
    cores = im.getcolors(maxcolors=4096) or []
    opacas = [(n, c) for n, c in cores if c[3] > 0]
    semi = sum(n for n, c in cores if 0 < c[3] < 255)
    orfaos = 0
    if w * h <= 256 * 256:
        for y in range(h):
            for x in range(w):
                c = px[x, y]
                if c[3] == 0:
                    continue
                viz = [px[x + dx, y + dy] for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                       if (dx or dy) and 0 <= x + dx < w and 0 <= y + dy < h]
                if viz and all(v != c for v in viz):
                    orfaos += 1
    top = ", ".join("#%02x%02x%02x" % c[:3] for n, c in sorted(opacas, reverse=True)[:12])
    return (f"tamanho {w}x{h} px; {len(opacas)} cores opacas (mais usadas: {top}); "
            f"{semi} pixels semitransparentes (anti-aliasing de borda); {orfaos} pixels isolados "
            "(cor diferente de todos os 8 vizinhos: possíveis pixels órfãos/ruído)")


def _preparar(img, pixel: bool, lado_max: int):
    from PIL import Image

    img = img.convert("RGBA") if img.mode in ("P", "LA", "RGBA", "PA") else img.convert("RGB")
    w, h = img.size
    if pixel and max(w, h) < LADO_PIXEL_ART:
        f = max(1, LADO_PIXEL_ART // max(w, h))
        img = img.resize((w * f, h * f), Image.NEAREST)
    elif max(w, h) > lado_max:
        f = lado_max / max(w, h)
        img = img.resize((max(1, int(w * f)), max(1, int(h * f))), Image.LANCZOS)
    return img


def _quadrantes(img) -> List:
    w, h = img.size
    m = 0.08  # pequena sobreposição para não cortar objetos ao meio
    caixas = [(0, 0, .5 + m, .5 + m), (.5 - m, 0, 1, .5 + m), (0, .5 - m, .5 + m, 1), (.5 - m, .5 - m, 1, 1)]
    return [img.crop((int(a * w), int(b * h), int(c * w), int(d * h))) for a, b, c, d in caixas]


def data_url(img, max_bytes: int = 0) -> str:
    """Imagem -> data URL (PNG se tiver transparência; senão JPEG). Sem EXIF (não vaza GPS)."""
    buf = io.BytesIO()
    if img.mode == "RGBA" and not max_bytes:
        img.save(buf, "PNG", optimize=True)
        mime = "png"
    else:
        im = img.convert("RGB")
        q = 90
        while True:
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q)
            if not max_bytes or buf.tell() <= max_bytes or q <= 40:
                break
            q -= 10
            if q <= 60:
                im = im.resize((max(1, int(im.width * .8)), max(1, int(im.height * .8))))
        mime = "jpeg"
    return f"data:image/{mime};base64," + base64.b64encode(buf.getvalue()).decode()


@dataclass
class Vistas:
    partes: List[dict]
    info: str
    pixel: bool
    recortes: List[dict] = field(default_factory=list)  # quadrantes ampliados (só imagem única, modo minucioso)
    medidas: List[str] = field(default_factory=list)  # pixel art: números calculados pelo NLR

    @property
    def total(self) -> int:
        return len(self.partes) + len(self.recortes)


def montar_vistas(caminhos: Sequence[Path], modo: str, cfg) -> Vistas:
    """Monta as partes multimodais (OpenAI image_url) para 1+ imagens."""
    lado = max(256, int(getattr(cfg.visao, "lado_max", 1536) or 1536))
    partes: List[dict] = []
    recortes: List[dict] = []
    medidas: List[str] = []
    infos: List[str] = []
    algum_pixel = False
    varias = len(caminhos) > 1
    for p in caminhos:
        img, exif = abrir_imagem(p)
        pixel = modo == "pixel" or eh_pixel_art(img)
        algum_pixel = algum_pixel or pixel
        w, h = img.size
        imagens = [_preparar(img, pixel, lado if not varias else min(lado, 1024))]
        if (modo == "minucioso" and not varias and not pixel and cfg.visao.recortes and max(w, h) > LIMIAR_QUADRANTES):
            recortes = [{"type": "image_url", "image_url": {"url": data_url(_preparar(q, False, min(lado, LADO_RECORTE)))}}
                        for q in _quadrantes(img)]
        info = f"{p.name}: {w}x{h} px, modo {img.mode}" + (", parece pixel art" if pixel else "")
        if pixel and modo == "pixel" and max(w, h) <= 512:
            try:
                medidas.append(f"{p.name}: {medidas_pixel_art(img)}")
            except Exception:  # noqa: BLE001
                pass
        if exif:
            info += "; EXIF: " + ", ".join(f"{k}={v}" for k, v in exif.items())
        infos.append(info)
        partes += [{"type": "image_url", "image_url": {"url": data_url(i)}} for i in imagens]
    return Vistas(partes=partes, info=" | ".join(infos), pixel=algum_pixel, recortes=recortes, medidas=medidas)


# ====================================================================== chamada ao modelo
def perguntar_modelo(llm, cfg, partes: List[dict], instrucao: str, *, modelo: str = "", max_tokens: int = 0,
                     ao_receber: Optional[Callable[[str], None]] = None, historico: Optional[List[dict]] = None) -> str:
    from ..i18n import idioma_atual

    sistema = t("visao.prompt_sistema")
    msgs = [{"role": "system", "content": sistema}] + list(historico or []) + \
        [{"role": "user", "content": [{"type": "text", "text": instrucao}] + partes}]
    if idioma_atual() == "en":
        msgs[-1]["content"][0]["text"] += "\n\nAnswer in English."
    try:
        return limpar_repeticoes(llm.chat(msgs, modelo=modelo or None, max_tokens=max_tokens or cfg.visao.max_tokens,
                                          temperatura=0.2, ao_receber=ao_receber, extras=EXTRAS_ANTIREPETICAO))
    except AgenteErro as e:
        nome = modelo or cfg.modelo.modelo_chat
        msg = str(e)
        if any(x in msg.lower() for x in ("image", "vision", "multimodal", "mmproj", "image_url")):
            raise AgenteErro(f"{msg}\n\n{t('visao.sem_visao', modelo=nome)}") from e
        raise AgenteErro(f"{msg}\nDica: o modelo '{nome}' precisa ter visão (ex.: Qwen2.5-VL, Gemma 3, LLaVA). "
                         "Defina modelo.modelo_visao no config.yaml e confira com: nlr imagem status") from e


# Modelos de visão pequenos (3-4B) entram em laço ("- Pêlos claros... - Pêlos claros..."): penalidade de
# repetição (llama.cpp/LM Studio: repeat_penalty; padrão OpenAI: frequency_penalty) + limpeza da saída.
EXTRAS_ANTIREPETICAO = {"repeat_penalty": 1.12, "frequency_penalty": 0.3}


def limpar_repeticoes(texto: str, max_iguais: int = 1) -> str:
    """Remove linhas repetidas (mesmo conteúdo) que modelos pequenos geram em laço; corta a linha final truncada."""
    out, vistos = [], {}
    for linha in (texto or "").splitlines():
        chave = " ".join(linha.lower().split()).strip("-*•. ")
        if len(chave) > 12 and not linha.lstrip().startswith(("```", "|")):
            vistos[chave] = vistos.get(chave, 0) + 1
            if vistos[chave] > max_iguais:
                continue
        out.append(linha)
    return "\n".join(out).strip()


def _modelo_para_uso(llm, cfg, avisos: List[str]) -> str:
    est = estado_visao(llm, cfg)
    if est.erro:
        raise AgenteErro(est.erro)
    avisos.extend(est.avisos)
    return est.modelo


@dataclass
class ResultadoVisao:
    texto: str
    info: str
    modo: str
    modelo: str
    vistas: int
    avisos: List[str] = field(default_factory=list)
    fontes: List[Fonte] = field(default_factory=list)
    consultas: List[str] = field(default_factory=list)
    descricao: str = ""
    reversa: bool = False

    def dict(self) -> dict:
        d = asdict(self)
        d["fontes"] = [{"n": f.n, "tipo": f.tipo, "titulo": f.titulo, "referencia": f.referencia, "local": f.local,
                        "trecho": f.texto[:400]} for f in self.fontes]
        return d


def _caminhos(c: Union[Path, str, Sequence]) -> List[Path]:
    if isinstance(c, (str, Path)):
        return [Path(c)]
    return [Path(x) for x in c]


def analisar(llm, cfg, caminhos, modo: str = "", pergunta: str = "", *, ao_receber=None, eventos=None,
             historico: Optional[List[dict]] = None) -> ResultadoVisao:
    """Analisa 1+ imagens (caminhos já autorizados). modo: minucioso | geral | texto | pixel."""
    eventos = eventos or (lambda tipo, msg: None)
    ps = _caminhos(caminhos)[: max(1, cfg.visao.max_imagens)]
    explicito = modo in MODOS
    modo = modo if explicito else (cfg.visao.modo_padrao if cfg.visao.modo_padrao in MODOS else "minucioso")
    avisos: List[str] = []
    modelo = _modelo_para_uso(llm, cfg, avisos)
    for a in avisos:
        eventos("aviso", a)
    v = montar_vistas(ps, modo, cfg)
    if v.pixel and not explicito and len(ps) == 1 and not pergunta.strip():
        modo = "pixel"  # sprite pequeno: a revisão de pixel art é mais útil que a análise de foto
    instrucao = (PROMPT_VARIAS.format(n=len(ps)) + "\n" + PROMPTS[modo]) if len(ps) > 1 else PROMPTS[modo]
    if modo == "pixel" and not v.medidas:  # modo trocado para pixel depois de montar: calcula agora
        try:
            from PIL import Image  # noqa: F401

            v.medidas = [f"{p.name}: {medidas_pixel_art(abrir_imagem(p)[0])}" for p in ps if max(abrir_imagem(p)[0].size) <= 512]
        except Exception:  # noqa: BLE001
            pass
    if modo == "pixel" and v.medidas:
        instrucao += "\n\nMEDIDAS OBJETIVAS:\n" + "\n".join(v.medidas)
    if pergunta.strip():
        instrucao += f"\n\nPergunta do usuário (responda a ela primeiro, com base no que é VISTO): {pergunta.strip()}"
    eventos("status", f"Analisando imagem ({modo}, {v.total} vista(s)) com {modelo}...")
    if modo == "minucioso" and v.recortes:
        notas = []
        for i, (reg, parte) in enumerate(zip(REGIOES, v.recortes), 1):
            eventos("status", f"Olhando de perto o quadrante {reg} ({i}/{len(v.recortes)})...")
            n = perguntar_modelo(llm, cfg, [parte], PROMPT_RECORTE.format(regiao=reg), modelo=modelo, max_tokens=350)
            notas.append(f"[{reg}]\n{n.strip()}")
        instrucao = PROMPT_FINAL_MINUCIOSO.format(notas="\n\n".join(notas)) + instrucao.replace(
            "A primeira imagem é a visão geral; as seguintes (se houver) são recortes ampliados dos quadrantes "
            "(superior-esquerdo, superior-direito, inferior-esquerdo, inferior-direito). ", "")
        eventos("status", "Juntando tudo na análise final...")
    texto = perguntar_modelo(llm, cfg, v.partes, instrucao, modelo=modelo, ao_receber=ao_receber, historico=historico)
    return ResultadoVisao(texto=texto, info=v.info, modo=modo, modelo=modelo, vistas=v.total, avisos=avisos)


# ====================================================================== pesquisa pela imagem
class AnaliseBusca(BaseModel):
    descricao: str = ""
    texto_visivel: str = ""
    tem_pessoas: bool = False
    consultas: List[str] = Field(default_factory=list)


INSTR_BUSCA = (
    "Olhe a imagem para planejar uma pesquisa na internet sobre ela. Responda SÓ com JSON no formato "
    '{"descricao": "...", "texto_visivel": "...", "tem_pessoas": false, "consultas": ["...", "..."]}. '
    "Em 'consultas', dê de 1 a 3 buscas curtas e específicas (nomes, marcas, modelos, lugares, texto legível, "
    "espécie, estilo artístico), da mais específica para a mais geral. 'tem_pessoas' = true se houver pessoas "
    "reais em destaque. Nunca tente identificar pessoas pelo rosto nem ponha nomes de pessoas nas consultas.")

PROMPT_SINTESE = (
    "Você recebeu a descrição de uma imagem (feita por um modelo de visão) e resultados da web. Responda ao objetivo "
    "do usuário sobre a imagem. Regras: use SÓ as fontes; cite com [n] logo após cada afirmação; separe o que é "
    "CONFIRMADO pelas fontes do que é PROVÁVEL; se as fontes não confirmarem, diga isso claramente. "
    "Não identifique pessoas pelo rosto. Seja objetivo (até ~250 palavras).")


def _limpar_frase(x: str) -> str:
    import re

    x = re.sub(r"(^|\s)\d+[.)]\s*", " ", x or "")
    x = re.sub(r"[*#`\"{}\[\]]", " ", x)
    return " ".join(x.split())


def _consultas(an: AnaliseBusca, foco: str, bruto: str) -> List[str]:
    cs: List[str] = []
    for c in an.consultas:
        c = _limpar_frase(c) if isinstance(c, str) else ""
        if c and c.lower() not in {x.lower() for x in cs}:
            cs.append(c[:120])
    if not cs:  # modelo não devolveu consultas: monta a partir da descrição (sem copiar a pergunta inteira)
        desc = _limpar_frase(an.descricao or bruto)
        primeira = desc.split(". ")[0].split(",")[0]
        if primeira:
            cs.append(" ".join(primeira.split()[:8]))
        if an.texto_visivel.strip():
            cs.append(" ".join(_limpar_frase(an.texto_visivel).split()[:10]))
        if foco.strip() and primeira:
            cs.append(" ".join((" ".join(primeira.split()[:5]) + " " + foco).split()[:12]))
    return cs[:3]


def _planejar_busca(llm, cfg, partes: List[dict], foco: str, modelo: str) -> Tuple[AnaliseBusca, str]:
    """Pede ao modelo de visão o JSON (descrição, texto, pessoas, consultas). Usa saída estruturada quando o
    servidor suporta (LM Studio/llama.cpp/Ollama) e cai para texto livre se não der."""
    instr = INSTR_BUSCA + (f"\nObjetivo do usuário: {foco}" if foco.strip() else "")
    msgs = [{"role": "system", "content": t("visao.prompt_sistema")},
            {"role": "user", "content": [{"type": "text", "text": instr}] + partes}]
    try:
        an = llm.chat_json(msgs, AnaliseBusca, modelo=modelo, max_tokens=600, tentativas=2)
        return an, an.descricao
    except AgenteErro:
        pass
    bruto = perguntar_modelo(llm, cfg, partes, instr, modelo=modelo, max_tokens=700)
    dado = extrair_json(bruto)
    try:
        an = AnaliseBusca.model_validate(dado if isinstance(dado, dict) else {})
    except Exception:  # noqa: BLE001
        an = AnaliseBusca()
    if not an.descricao:
        an.descricao = _limpar_frase(bruto)[:600]
    return an, bruto


def _sintetizar(llm, foco: str, an: AnaliseBusca, fontes: List[Fonte], modelo: str, ao_receber=None) -> str:
    from ..i18n import instrucao_idioma

    pergunta = foco or "o que é isto e o que as fontes dizem sobre isso"
    for n, tam, extras in ((6, 700, EXTRAS_ANTIREPETICAO), (4, 450, None)):
        blocos = "\n\n".join(f.bloco(tam) for f in fontes[:n])
        msgs = [{"role": "system", "content": "Você responde perguntas sobre uma imagem usando fontes da web. "
                                              + instrucao_idioma()},
                {"role": "user", "content": f"FONTES:\n{blocos}\n\nDescrição da imagem: {an.descricao}\n"
                                            + (f"Texto visível: {an.texto_visivel}\n" if an.texto_visivel else "")
                                            + f"\n{PROMPT_SINTESE}\n\nPergunta: {pergunta}"}]
        try:
            r = limpar_repeticoes(llm.chat(msgs, modelo=modelo, max_tokens=900, temperatura=0.2,
                                           ao_receber=ao_receber, extras=extras))
        except AgenteErro as e:
            return f"(não consegui escrever a síntese: {e})"
        if r.strip():
            return r
    return "O modelo não escreveu uma síntese. Veja as fontes: " + "; ".join(f"[{f.n}] {f.titulo}" for f in fontes[:3])


def busca_reversa_serpapi(caminho: Path, cfg, ctx_web=None) -> List[Fonte]:
    """Google Lens oficial via SerpApi (upload da imagem reduzida, sem EXIF). Só roda com consentimento + chave."""
    import requests

    br = cfg.visao.busca_reversa
    chave = os.environ.get(br.api_key_env or "SERPAPI_API_KEY", "")
    img, _ = abrir_imagem(caminho)
    url = data_url(_preparar(img, False, 1024), max_bytes=480_000)
    dados = base64.b64decode(url.split(",", 1)[1])
    r = requests.post("https://serpapi.com/image", files={"image": ("imagem.jpg", dados, "image/jpeg")},
                      data={"api_key": chave}, timeout=60)
    r.raise_for_status()
    image_id = r.json().get("image_id")
    if not image_id:
        raise AgenteErro(f"SerpApi não devolveu image_id: {r.text[:200]}")
    hl = "en" if cfg.idioma == "en" else "pt-BR"
    r = requests.get("https://serpapi.com/search.json", params={"engine": "google_lens", "image_id": image_id,
                                                                 "api_key": chave, "hl": hl}, timeout=60)
    r.raise_for_status()
    d = r.json()
    if d.get("error"):
        raise AgenteErro(str(d["error"])[:200])
    fontes: List[Fonte] = []
    for kg in (d.get("knowledge_graph") or [])[:2]:
        if kg.get("title") and kg.get("link"):
            fontes.append(Fonte(n=0, tipo="web", titulo=f"Google Lens: {kg['title']}", referencia=kg["link"],
                                texto=" ".join(str(kg.get(k, "")) for k in ("title", "subtitle", "description")).strip()))
    for m in (d.get("visual_matches") or [])[: max(1, br.max_resultados)]:
        if m.get("link"):
            fontes.append(Fonte(n=0, tipo="web", titulo=m.get("title") or m.get("source") or m["link"],
                                referencia=m["link"], texto=f"Imagem parecida em {m.get('source', '')}: {m.get('title', '')}".strip()))
    if ctx_web is not None and fontes and br.paginas_para_ler > 0:
        try:  # lê as primeiras páginas para ter trechos citáveis de verdade
            from ..web.busca import ResultadoBusca

            res = [ResultadoBusca(f.titulo, f.referencia, f.texto) for f in fontes[: br.paginas_para_ler]]
            lidas = ctx_web.selecionar(" ".join(f.titulo for f in fontes[:3]), ctx_web.ler_paginas(res))
            if lidas:
                fontes = lidas + fontes[br.paginas_para_ler:]
        except Exception:  # noqa: BLE001
            pass
    return fontes


def _pode_reversa(cfg, an: AnaliseBusca, avisos: List[str]) -> bool:
    br = cfg.visao.busca_reversa
    if br.provedor != "serpapi":
        return False
    if not br.consentimento_envio:
        avisos.append(t("visao.reversa_sem_consentimento"))
        return False
    if not os.environ.get(br.api_key_env or "SERPAPI_API_KEY"):
        avisos.append(t("visao.reversa_sem_chave", var=br.api_key_env))
        return False
    if an.tem_pessoas:
        avisos.append(t("visao.pessoas"))
        return False
    return True


def pesquisar(llm, cfg, web, caminho, foco: str = "", *, ao_receber=None, eventos=None, sintetizar: bool = True,
              adicionar_fontes: Optional[Callable[[List[Fonte]], List[Fonte]]] = None) -> ResultadoVisao:
    """Descreve a imagem, pesquisa na web (e, se ligado, faz a busca reversa) e responde citando [n]."""
    eventos = eventos or (lambda tipo, msg: None)
    p = _caminhos(caminho)[0]
    avisos: List[str] = []
    modelo = _modelo_para_uso(llm, cfg, avisos)
    for a in avisos:
        eventos("aviso", a)
    v = montar_vistas([p], "geral", cfg)
    eventos("status", "Identificando a imagem para pesquisar...")
    an, bruto = _planejar_busca(llm, cfg, v.partes, foco, modelo)
    consultas = _consultas(an, foco, bruto)
    fontes: List[Fonte] = []
    reversa = False
    if _pode_reversa(cfg, an, avisos):
        eventos("status", "Busca reversa (Google Lens via SerpApi)...")
        try:
            fontes += busca_reversa_serpapi(p, cfg, web)
            reversa = True
        except Exception as e:  # noqa: BLE001
            avisos.append(t("visao.reversa_falhou", erro=str(e)[:160]))
    for c in consultas:
        try:
            fontes += web.pesquisar(c, status=lambda s: eventos("status", s))[:4]
        except Exception as e:  # noqa: BLE001
            eventos("status", f"Busca '{c}' falhou: {e}")
    vistos, unicas = set(), []
    for f in fontes:  # sem URLs repetidas
        if f.referencia in vistos:
            continue
        vistos.add(f.referencia)
        unicas.append(f)
    unicas = unicas[:10]
    fontes = adicionar_fontes(unicas) if adicionar_fontes else _renumerar(unicas)
    cab = (f"**O que a imagem mostra:** {an.descricao}\n"
           + (f"**Texto visível:** {an.texto_visivel}\n" if an.texto_visivel else "")
           + f"**Buscas feitas:** {'; '.join(consultas) or '(nenhuma)'}" + (" + busca reversa" if reversa else "") + "\n")
    res = ResultadoVisao(texto=cab, info=v.info, modo="pesquisa", modelo=modelo, vistas=v.total, avisos=avisos,
                         fontes=fontes, consultas=consultas, descricao=an.descricao, reversa=reversa)
    if not fontes:
        res.texto = cab + "\nA busca não trouxe resultados. Tente outra pergunta (foco) ou a análise minuciosa."
        if ao_receber:
            ao_receber(res.texto)
        return res
    if not sintetizar:
        res.texto = cab + "\nResultados da web (cite como [n]):\n\n" + "\n\n".join(f.bloco(1000) for f in fontes)
        return res
    eventos("status", "Escrevendo a resposta com as fontes...")
    if ao_receber:
        ao_receber(cab + "\n")
    resposta = _sintetizar(llm, foco, an, fontes, modelo, ao_receber)
    res.texto = cab + "\n" + resposta
    return res


def _renumerar(fontes: List[Fonte]) -> List[Fonte]:
    for i, f in enumerate(fontes):
        f.n = i + 1
    return fontes


# ====================================================================== ferramentas do agente
def _caminho_ctx(ctx, caminho: str) -> Path:
    return ctx.politica.checar_leitura(caminho)


class ArgsAnalisar(BaseModel):
    caminho: str = Field(description="caminho da imagem (png, jpg, webp, gif, bmp, tiff)")
    modo: str = Field("minucioso", description="geral | minucioso | texto (transcrever) | pixel (revisar pixel art)")
    pergunta: str = Field("", description="pergunta específica sobre a imagem (opcional)")


@ferramenta("analisar_imagem", "Analisa uma imagem com o modelo de visão local (descrição minuciosa, texto, pixel art).",
            permissao="leitura", grupos={"pesquisa", "arquivos", "util"})
def analisar_imagem(ctx, a: ArgsAnalisar) -> str:
    p = _caminho_ctx(ctx, a.caminho)
    r = analisar(ctx.llm, ctx.cfg, [p], a.modo if a.modo in MODOS else "minucioso", a.pergunta, eventos=ctx.evento)
    return f"[{r.info}; {r.vistas} vista(s)]\n\n{r.texto}"


class ArgsBuscarImagem(BaseModel):
    caminho: str = Field(description="caminho da imagem")
    foco: str = Field("", description="o que você quer descobrir (ex.: 'que planta é essa', 'onde comprar')")


@ferramenta("pesquisar_por_imagem",
            "Identifica o conteúdo de uma imagem com o modelo de visão e pesquisa na internet sobre ele (cite como [n]).",
            permissao="rede", grupos={"pesquisa"})
def pesquisar_por_imagem(ctx, a: ArgsBuscarImagem) -> str:
    p = _caminho_ctx(ctx, a.caminho)
    r = pesquisar(ctx.llm, ctx.cfg, ctx.web, p, a.foco, eventos=ctx.evento, sintetizar=False,
                  adicionar_fontes=ctx.adicionar_fontes)
    if not r.fontes:
        return f"[{r.info}]\n{r.texto}\nUse analisar_imagem e uma consulta própria em buscar_web."
    return f"[{r.info}]\n{r.texto}"
