"""Embeddings pelo próprio servidor de modelos (Ollama, LM Studio, llama.cpp ou API), com prefixos por modelo."""
from __future__ import annotations

from typing import List, Optional

from ..config import Config
from ..llm.cliente import ClienteLLM


def prefixos_padrao(modelo: str):
    n = modelo.lower()
    if "nomic" in n:
        return "search_query: ", "search_document: "
    if "e5" in n:
        return "query: ", "passage: "
    if "qwen3-embedding" in n or "qwen3_embedding" in n:
        return "Instruct: Dada uma pergunta, encontre trechos relevantes que a respondam\nQuery: ", ""
    if "embeddinggemma" in n:
        return "task: search result | query: ", "title: none | text: "
    return "", ""


class EmbedderServidor:
    def __init__(self, cfg: Config, llm: ClienteLLM):
        self.llm = llm
        self.modelo = cfg.modelo.modelo_embeddings
        self.id = f"{cfg.modelo.backend}:{self.modelo}"
        self.pref_q, self.pref_d = prefixos_padrao(self.modelo)
        self.lote = max(1, cfg.biblioteca.lote_embeddings)

    def documentos(self, textos: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(textos), self.lote):
            out += self.llm.embeddings([self.pref_d + t[:8000] for t in textos[i:i + self.lote]])
        return out

    def consulta(self, texto: str) -> List[float]:
        return self.llm.embeddings([self.pref_q + texto])[0]


def criar_embedder(cfg: Config, llm: Optional[ClienteLLM]):
    if cfg.biblioteca.embeddings == "nenhum" or llm is None or not cfg.modelo.modelo_embeddings:
        return None
    return EmbedderServidor(cfg, llm)
