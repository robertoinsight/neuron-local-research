"""Descobre os modelos do servidor: quais estão carregados, qual é chat ou embeddings e o contexto REAL.

* LM Studio: /api/v0/models (state=loaded|not-loaded, type=llm|vlm|embeddings, max/loaded_context_length).
  O /v1/models do LM Studio lista TODOS os modelos baixados (por causa do JIT), por isso o antigo "auto"
  pegava um modelo não carregado.
* Ollama: /api/tags (baixados), /api/ps (carregados), /api/show (context_length e num_ctx).
* llama.cpp (llama-server): /props (n_ctx) e /v1/models.
* Outros (OpenAI-compatível): /v1/models; contexto pela tabela de nomes conhecidos ou o valor do config.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import List, Optional, Tuple

import requests

log = logging.getLogger(__name__)

_EMB = re.compile(r"embed|bge-|e5-|gte-|minilm|nomic-embed|arctic-embed|rerank", re.I)


@dataclass
class InfoModelo:
    id: str
    tipo: str = "chat"  # chat | embeddings | visao
    carregado: bool = False
    contexto_max: int = 0
    contexto_carregado: int = 0
    parametros_b: float = 0.0
    tamanho_bytes: int = 0
    visao: bool = False  # aceita imagens (LM Studio: type "vlm"/capabilities.vision; Ollama: "vision")
    visao_conhecida: bool = False  # o servidor informou a capacidade (senão, não dá para saber)

    def dict(self) -> dict:
        return asdict(self)

    @property
    def contexto(self) -> int:
        return self.contexto_carregado or self.contexto_max


def eh_embedding(nome: str) -> bool:
    return bool(_EMB.search(nome or ""))


def parametros_do_nome(nome: str) -> float:
    """'qwen3.5-9b' -> 9, 'gemma-4-e4b' -> 4, 'mixtral-8x7b' -> 56, 'qwen2.5:0.5b' -> 0.5."""
    n = (nome or "").lower()
    m = re.search(r"(\d+)x(\d+(?:\.\d+)?)b", n)
    if m:
        return float(m.group(1)) * float(m.group(2))
    m = re.search(r"(?:^|[^a-z0-9.])e?(\d+(?:\.\d+)?)b(?![a-z])", n.replace("_", "-"))
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)b\b", n)
    return float(m.group(1)) if m else 0.0


def _raiz(base_url: str) -> str:
    return re.sub(r"/v1/?$", "", base_url.rstrip("/"))


def _get(url: str, timeout: float = 5.0, metodo: str = "get", **kw):
    r = requests.request(metodo, url, timeout=timeout, **kw)
    r.raise_for_status()
    return r.json()


def _lmstudio(raiz: str) -> List[InfoModelo]:
    data = _get(f"{raiz}/api/v0/models").get("data", [])
    out = []
    for d in data:
        tp = str(d.get("type", "llm")).lower()
        tipo = {"embeddings": "embeddings", "embedding": "embeddings", "vlm": "visao"}.get(tp, "chat")
        caps = d.get("capabilities")
        visao = tp == "vlm" or (isinstance(caps, dict) and bool(caps.get("vision"))) or \
            (isinstance(caps, list) and "vision" in caps)
        out.append(InfoModelo(id=d["id"], tipo="visao" if visao and tipo == "chat" else tipo,
                              carregado=d.get("state") == "loaded",
                              contexto_max=int(d.get("max_context_length") or 0),
                              contexto_carregado=int(d.get("loaded_context_length") or 0),
                              parametros_b=parametros_do_nome(d["id"]), visao=visao, visao_conhecida=True))
    # LM Studio 0.4+: /api/v1/models traz capabilities.vision (mais confiável para Gemma 3/4 com visão)
    try:
        v1 = {m.get("key"): m for m in _get(f"{raiz}/api/v1/models", timeout=3).get("models", [])}
        for m in out:
            caps = (v1.get(m.id) or {}).get("capabilities") or {}
            if caps.get("vision") and not m.visao:
                m.visao = True
                if m.tipo == "chat":
                    m.tipo = "visao"
    except Exception:  # noqa: BLE001
        pass
    return out


def _ollama(raiz: str) -> List[InfoModelo]:
    tags = _get(f"{raiz}/api/tags").get("models", [])
    try:
        ps = {m["name"]: m for m in _get(f"{raiz}/api/ps").get("models", [])}
    except Exception:  # noqa: BLE001
        ps = {}
    out = []
    for m in tags:
        nome = m.get("name") or m.get("model")
        det = m.get("details") or {}
        tam = det.get("parameter_size", "")
        pb = parametros_do_nome(tam.lower()) if tam else parametros_do_nome(nome)
        if tam.upper().endswith("M"):
            try:
                pb = float(tam[:-1]) / 1000
            except ValueError:
                pass
        fam = " ".join([det.get("family", "")] + list(det.get("families") or [])).lower()
        tipo = "embeddings" if (eh_embedding(nome) or "bert" in fam) else ("visao" if "clip" in fam or "mllama" in fam else "chat")
        caps = m.get("capabilities")
        visao = tipo == "visao" or (isinstance(caps, list) and "vision" in caps)
        if visao and tipo == "chat":
            tipo = "visao"
        info = InfoModelo(id=nome, tipo=tipo, carregado=nome in ps, parametros_b=pb, tamanho_bytes=int(m.get("size") or 0),
                          visao=visao, visao_conhecida=isinstance(caps, list) or visao)
        if nome in ps and ps[nome].get("context_length"):
            info.contexto_carregado = int(ps[nome]["context_length"])
        out.append(info)
    return out


def contexto_ollama(raiz: str, modelo: str) -> Tuple[int, int]:
    """(contexto máximo do modelo, num_ctx configurado no Modelfile ou 0)."""
    d = _get(f"{raiz}/api/show", metodo="post", json={"model": modelo}, timeout=10)
    maximo = 0
    for k, v in (d.get("model_info") or {}).items():
        if k.endswith(".context_length"):
            maximo = int(v)
    num_ctx = 0
    m = re.search(r"num_ctx\s+(\d+)", d.get("parameters") or "")
    if m:
        num_ctx = int(m.group(1))
    return maximo, num_ctx


def _visao_openai(d: dict) -> Optional[bool]:
    """/v1/models de alguns servidores (llama.cpp recente, vLLM) diz se o modelo aceita imagem."""
    arq = d.get("architecture") or {}
    mods = arq.get("input_modalities") if isinstance(arq, dict) else None
    if isinstance(mods, list):
        return "image" in mods
    return None


def _llamacpp(raiz: str, base_url: str) -> List[InfoModelo]:
    ctx, visao = 0, None
    try:
        p = _get(f"{raiz}/props")
        ctx = int((p.get("default_generation_settings") or {}).get("n_ctx") or p.get("n_ctx") or 0)
        if isinstance(p.get("modalities"), dict):
            visao = bool(p["modalities"].get("vision"))
    except Exception:  # noqa: BLE001
        pass
    out = []
    for d in _get(f"{base_url}/models").get("data", []):
        i = d["id"]
        v = visao if visao is not None else _visao_openai(d)
        emb = eh_embedding(i)
        out.append(InfoModelo(id=i, tipo="embeddings" if emb else ("visao" if v else "chat"), carregado=True,
                              contexto_carregado=ctx, parametros_b=parametros_do_nome(i), visao=bool(v),
                              visao_conhecida=v is not None))
    return out


def _generico(base_url: str, api_key: str = "") -> List[InfoModelo]:
    h = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    out = []
    for d in _get(f"{base_url}/models", headers=h).get("data", []):
        i = d["id"]
        v = _visao_openai(d)
        out.append(InfoModelo(id=i, tipo="embeddings" if eh_embedding(i) else ("visao" if v else "chat"), carregado=False,
                              parametros_b=parametros_do_nome(i), visao=bool(v), visao_conhecida=v is not None))
    return out


def listar(backend: str, base_url: str, api_key: str = "") -> List[InfoModelo]:
    """Lista modelos com o máximo de informação que o servidor oferece. Lança exceção se o servidor estiver fora."""
    raiz = _raiz(base_url)
    if backend == "lmstudio":
        try:
            return _lmstudio(raiz)
        except Exception as e:  # noqa: BLE001  (versões antigas sem /api/v0)
            log.info("LM Studio sem /api/v0 (%s); usando /v1/models", e)
    elif backend == "ollama":
        try:
            return _ollama(raiz)
        except Exception as e:  # noqa: BLE001
            log.info("Ollama sem /api/tags (%s)", e)
    elif backend == "llamacpp":
        return _llamacpp(raiz, base_url)
    return _generico(base_url, api_key)


@dataclass
class Escolha:
    chat: str
    embeddings: str
    contexto: int
    avisos: List[str]
    info_chat: Optional[InfoModelo] = None


def escolher(modelos: List[InfoModelo], chat: str, embeddings: str, backend: str = "") -> Escolha:
    """Resolve "auto": prefere modelo CARREGADO; se não houver, o maior chat disponível que caiba e avisa."""
    from ..i18n import t

    avisos: List[str] = []
    chats = [m for m in modelos if m.tipo in ("chat", "visao") and not eh_embedding(m.id)]
    embs = [m for m in modelos if m.tipo == "embeddings" or eh_embedding(m.id)]
    info = None
    if chat in ("", "auto"):
        carregados = [m for m in chats if m.carregado]
        if carregados:
            info = carregados[0]
            avisos.append(t("modelo.auto_carregado", modelo=info.id))
        elif chats:
            from .hardware import detectar

            lim = detectar().max_parametros_b()
            cabem = [m for m in chats if 0 < m.parametros_b <= lim] or [m for m in chats if m.parametros_b == 0] or chats
            info = sorted(cabem, key=lambda m: m.parametros_b, reverse=True)[0]
            avisos.append(t("modelo.auto_escolhido", modelo=info.id))
        else:
            from ..erros import AgenteErro

            raise AgenteErro(t("modelo.sem_chat", backend=backend))
        chat = info.id
    else:
        info = next((m for m in modelos if m.id == chat), None)
        if info is None and modelos:
            # tolera diferenças como "qwen2.5:0.5b" vs "qwen2.5:0.5b:latest" ou caixa
            alvo = chat.lower().removesuffix(":latest")
            info = next((m for m in modelos if m.id.lower().removesuffix(":latest") == alvo), None)
            if info is None:
                avisos.append(t("modelo.nao_encontrado", modelo=chat, backend=backend,
                                lista=", ".join(m.id for m in chats[:8])))
    if embeddings == "auto":
        carreg = [m for m in embs if m.carregado] or embs
        embeddings = carreg[0].id if carreg else ""
        if embeddings:
            avisos.append(t("modelo.emb_escolhido", modelo=embeddings))
    return Escolha(chat=chat, embeddings=embeddings, contexto=info.contexto if info else 0, avisos=avisos, info_chat=info)
