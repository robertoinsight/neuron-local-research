"""Pesquisa na internet sem chave de API (ddgs ou SearXNG), leitura de páginas e seleção de trechos citáveis.

Somente leitura: as ferramentas de rede fazem apenas GET; nada é enviado ou publicado.
Resultados e páginas ficam em cache (SQLite) por web.cache_horas para poupar o buscador.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, List, Optional

import requests

from ..biblioteca.fatiamento import fatiar_texto
from ..config import Config
from ..erros import AgenteErro
from ..fontes import Fonte
from ..textutil import bm25

log = logging.getLogger(__name__)
logging.getLogger("trafilatura").setLevel(logging.ERROR)
_MAX_BYTES = 3_000_000


@dataclass
class ResultadoBusca:
    titulo: str
    url: str
    resumo: str


@dataclass
class Pagina:
    resultado: ResultadoBusca
    texto: str
    baixada: bool


class CacheWeb:
    def __init__(self, caminho: Path, horas: float):
        self.ttl = horas * 3600
        self._lock = threading.Lock()
        self.con = sqlite3.connect(str(caminho), check_same_thread=False)
        self.con.execute("CREATE TABLE IF NOT EXISTS cache (chave TEXT PRIMARY KEY, valor TEXT, criado REAL)")

    def get(self, chave: str):
        if self.ttl <= 0:
            return None
        with self._lock:
            r = self.con.execute("SELECT valor, criado FROM cache WHERE chave=?", (chave,)).fetchone()
        if r and time.time() - r[1] < self.ttl:
            return json.loads(r[0])
        return None

    def put(self, chave: str, valor) -> None:
        if self.ttl <= 0:
            return
        with self._lock:
            self.con.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (chave, json.dumps(valor, ensure_ascii=False), time.time()))
            self.con.commit()


class PesquisaWeb:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cache = CacheWeb(cfg.dir_dados / "cache_web.db", cfg.web.cache_horas)

    # ------------------------------------------------------------ busca
    def _ddgs(self, consulta: str) -> List[ResultadoBusca]:
        try:
            from ddgs import DDGS
        except ImportError as e:
            raise AgenteErro("Instale o pacote de busca: pip install ddgs") from e
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                bruto = DDGS().text(consulta, region=self.cfg.web.regiao, max_results=self.cfg.web.max_resultados)
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "No results" in msg:
                    return []
                raise AgenteErro(
                    "A busca na web falhou (limite de requisições do buscador ou sem internet).\n"
                    f"Detalhe: {msg[:200]}\nTente de novo em instantes ou configure um SearXNG (web.motor: searxng)."
                ) from e
        out = []
        for r in bruto or []:
            url = r.get("href") or r.get("url")
            if url:
                out.append(ResultadoBusca(r.get("title", "") or url, url, r.get("body", "") or ""))
        return out

    def _searxng(self, consulta: str) -> List[ResultadoBusca]:
        base = self.cfg.web.searxng_url.rstrip("/")
        if not base:
            raise AgenteErro("web.motor é 'searxng', mas web.searxng_url está vazio no config.yaml.")
        try:
            r = requests.get(f"{base}/search", params={"q": consulta, "format": "json", "language": "pt-BR"},
                             timeout=self.cfg.web.timeout, headers={"User-Agent": self.cfg.web.user_agent})
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            raise AgenteErro(f"Não consegui acessar o SearXNG em {base}: {e}") from e
        except ValueError as e:
            raise AgenteErro("O SearXNG não devolveu JSON. Ative 'json' em search.formats no settings.yml.") from e
        return [ResultadoBusca(x.get("title") or x["url"], x["url"], x.get("content", "") or "")
                for x in data.get("results", [])[: self.cfg.web.max_resultados] if x.get("url")]

    def buscar(self, consulta: str) -> List[ResultadoBusca]:
        chave = f"busca:{self.cfg.web.motor}:{self.cfg.web.regiao}:{consulta}"
        em_cache = self.cache.get(chave)
        if em_cache is not None:
            return [ResultadoBusca(**x) for x in em_cache]
        motor = self.cfg.web.motor.lower()
        if motor == "searxng":
            res = self._searxng(consulta)
        elif motor in ("ddgs", "duckduckgo"):
            res = []
            for espera in (0, 2, 5):  # o buscador às vezes devolve vazio/erro por limite de requisições
                if espera:
                    time.sleep(espera)
                try:
                    res = self._ddgs(consulta)
                except AgenteErro:
                    if espera == 5:
                        raise
                    continue
                if res:
                    break
        else:
            raise AgenteErro(f"web.motor desconhecido: '{self.cfg.web.motor}' (use 'ddgs' ou 'searxng').")
        if res:
            self.cache.put(chave, [asdict(r) for r in res])
        return res

    # ------------------------------------------------------------ leitura
    def _baixar(self, url: str) -> Optional[bytes]:
        try:
            r = requests.get(url, timeout=self.cfg.web.timeout, stream=True,
                             headers={"User-Agent": self.cfg.web.user_agent,
                                      "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5"})
            r.raise_for_status()
            tipo = r.headers.get("Content-Type", "").lower()
            if "html" not in tipo and "text/plain" not in tipo and "xml" not in tipo:
                r.close()
                return None
            corpo = r.raw.read(_MAX_BYTES, decode_content=True)
            r.close()
            return corpo
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def extrair_texto(html, url: str = "") -> str:
        import trafilatura

        txt = trafilatura.extract(html, url=url or None, include_comments=False, include_tables=True, favor_recall=True)
        return (txt or "").strip()

    def _para_pagina(self, res: ResultadoBusca, corpo: Optional[bytes]) -> Pagina:
        if corpo is None:
            return Pagina(res, res.resumo, False)
        try:
            texto = self.extrair_texto(corpo, res.url)
        except Exception:  # noqa: BLE001
            texto = ""
        if len(texto) < 200:
            return Pagina(res, (texto + "\n" + res.resumo).strip() if texto else res.resumo, False)
        return Pagina(res, texto[: self.cfg.web.max_caracteres_pagina], True)

    def ler_pagina(self, url: str) -> Pagina:
        """Baixa e extrai o texto principal de uma URL (com cache)."""
        if not url.startswith(("http://", "https://")):
            raise AgenteErro("Só leio endereços http:// ou https://.")
        chave = f"pagina:{url}"
        c = self.cache.get(chave)
        if c is not None:
            return Pagina(ResultadoBusca(**c["resultado"]), c["texto"], c["baixada"])
        pg = self._para_pagina(ResultadoBusca(url, url, ""), self._baixar(url))
        if pg.baixada:
            self.cache.put(chave, {"resultado": asdict(pg.resultado), "texto": pg.texto, "baixada": True})
        return pg

    def ler_paginas(self, resultados: List[ResultadoBusca]) -> List[Pagina]:
        n = self.cfg.web.paginas_para_ler
        todo = resultados[:n]
        if not todo:
            return []
        with ThreadPoolExecutor(max_workers=min(6, len(todo))) as ex:
            corpos = list(ex.map(lambda r: self._baixar(r.url), todo))
        # extração em série: o parser nativo (lxml) mostrou instabilidade quando usado em paralelo
        paginas = [self._para_pagina(r, b) for r, b in zip(todo, corpos)]
        paginas += [Pagina(r, r.resumo, False) for r in resultados[n:]]
        return paginas

    # ------------------------------------------------------------ trechos citáveis
    def selecionar(self, consulta: str, paginas: List[Pagina], inicio: int = 1) -> List[Fonte]:
        itens = []
        for pi, pg in enumerate(paginas):
            if not pg.texto.strip():
                continue
            for ci, c in enumerate(fatiar_texto(pg.texto, self.cfg.web.tamanho_trecho, 120)):
                itens.append((pi, ci, c))
        if not itens:
            return []
        notas = bm25(consulta, [it[2] for it in itens])
        ordem = sorted(range(len(itens)), key=lambda i: (-notas[i], itens[i][0], itens[i][1]))
        por_pg: dict = {}
        escolhidos = []
        for i in ordem:
            pi = itens[i][0]
            if por_pg.get(pi, 0) >= self.cfg.web.max_trechos_por_pagina:
                continue
            por_pg[pi] = por_pg.get(pi, 0) + 1
            escolhidos.append(i)
            if len(escolhidos) >= self.cfg.web.max_trechos:
                break
        agrup: dict = {}
        for i in escolhidos:
            agrup.setdefault(itens[i][0], []).append(i)
        fontes: List[Fonte] = []
        for pi in sorted(agrup):
            idxs = sorted(agrup[pi], key=lambda i: itens[i][1])
            r = paginas[pi].resultado
            fontes.append(Fonte(n=inicio + len(fontes), tipo="web", titulo=r.titulo, referencia=r.url,
                                texto="\n[...]\n".join(itens[i][2] for i in idxs)))
        return fontes

    def pesquisar(self, consulta: str, inicio: int = 1, status: Optional[Callable[[str], None]] = None) -> List[Fonte]:
        status = status or (lambda s: None)
        status(f"Pesquisando na web: {consulta}")
        res = self.buscar(consulta)
        if not res:
            return []
        status(f"Lendo {min(len(res), self.cfg.web.paginas_para_ler)} página(s)...")
        return self.selecionar(consulta, self.ler_paginas(res), inicio)
