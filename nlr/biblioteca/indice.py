"""Índice da biblioteca em um único arquivo SQLite: FTS5 (BM25) + vetores (embeddings) + manifesto.

* Incremental: só reprocessa arquivos novos/alterados (tamanho, data e hash SHA-1) e remove os apagados.
* Funciona sem embeddings (busca só por palavras-chave) e completa os vetores depois (`nlr indexar --vetores`).
* Busca vetorial por força bruta em NumPy: rápida até ~200 mil trechos, sem servidor e sem dependências nativas.
"""
from __future__ import annotations

import fnmatch
import hashlib
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

import numpy as np

from ..config import Config
from ..erros import AgenteErro
from ..textutil import tokenizar
from .carregadores import CARREGADORES, carregar_arquivo
from .fatiamento import fatiar_segmentos

log = logging.getLogger(__name__)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS arquivos (
    caminho TEXT PRIMARY KEY, raiz TEXT, mtime REAL, tamanho INTEGER, hash TEXT,
    n_trechos INTEGER, indexado_em REAL, erro TEXT
);
CREATE TABLE IF NOT EXISTS trechos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, caminho TEXT, ordem INTEGER, local TEXT, texto TEXT, vetor BLOB
);
CREATE INDEX IF NOT EXISTS ix_trechos_caminho ON trechos(caminho);
CREATE VIRTUAL TABLE IF NOT EXISTS trechos_fts USING fts5(texto, nome, tokenize='unicode61 remove_diacritics 2');
"""


@dataclass
class Resultado:
    caminho: str
    local: str
    texto: str
    pontuacao: float
    raiz: str = ""

    @property
    def rotulo(self) -> str:
        nome = self.caminho
        if self.raiz:
            try:
                nome = str(Path(self.caminho).relative_to(self.raiz))
            except ValueError:
                pass
        return f"{nome}" + (f" ({self.local})" if self.local else "")


@dataclass
class RelatorioIndexacao:
    novos: int = 0
    atualizados: int = 0
    removidos: int = 0
    inalterados: int = 0
    trechos: int = 0
    erros: List[Tuple[str, str]] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)
    sem_vetor: int = 0
    aviso_embeddings: str = ""
    segundos: float = 0.0

    def resumo(self) -> str:
        s = (f"{self.novos} novo(s), {self.atualizados} atualizado(s), {self.removidos} removido(s), "
             f"{self.inalterados} sem mudança; {self.trechos} trecho(s) gerado(s) em {self.segundos:.1f}s.")
        if self.erros:
            s += f" {len(self.erros)} arquivo(s) com erro."
        if self.sem_vetor:
            s += f" {self.sem_vetor} trecho(s) sem vetor (só busca por palavras)."
        if self.avisos:
            s += " Avisos: " + "; ".join(self.avisos[:5])
        return s


def _consulta_fts(consulta: str) -> str:
    toks = tokenizar(consulta)
    return " OR ".join(f'"{t}"' for t in toks[:32])


def _hash(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


class IndiceBiblioteca:
    def __init__(self, cfg: Config, embedder=None, db: Optional[Path] = None):
        self.cfg = cfg
        self.embedder = embedder  # objeto com .id e .documentos(list[str]) / .consulta(str)
        self.db_path = Path(db or cfg.db_biblioteca)
        self._lock = threading.RLock()
        self.con = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.con.executescript(ESQUEMA)
        if "avisos" not in {r[1] for r in self.con.execute("PRAGMA table_info(arquivos)")}:  # v0.5
            self.con.execute("ALTER TABLE arquivos ADD COLUMN avisos TEXT DEFAULT ''")
            self.con.commit()
        self._cache_vet: Optional[Tuple[int, np.ndarray, np.ndarray]] = None  # (versão, ids, matriz)

    # ------------------------------------------------------------ meta
    def _meta(self, chave: str, padrao: str = "") -> str:
        r = self.con.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
        return r[0] if r else padrao

    def _set_meta(self, chave: str, valor: str) -> None:
        self.con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (chave, valor))

    def _versao(self) -> int:
        return int(self._meta("versao", "0"))

    def _incrementar_versao(self) -> None:
        self._set_meta("versao", str(self._versao() + 1))

    # ------------------------------------------------------------ varredura
    def _ignorado(self, rel_partes: Iterable[str], nome: str) -> bool:
        for padrao in self.cfg.biblioteca.ignorar:
            if any(fnmatch.fnmatch(p, padrao) for p in rel_partes) or fnmatch.fnmatch(nome, padrao):
                return True
        return False

    def varrer(self, pastas: Optional[List[Path]] = None) -> List[Tuple[Path, Path]]:
        """Lista (arquivo, raiz) suportados nas pastas da biblioteca."""
        exts = {e.lower() for e in self.cfg.biblioteca.extensoes} & set(CARREGADORES)
        max_bytes = self.cfg.biblioteca.max_arquivo_mb * 1024 * 1024
        out = []
        for raiz in pastas if pastas is not None else self.cfg.pastas_biblioteca():
            if not raiz.exists():
                log.warning("Pasta da biblioteca não existe: %s", raiz)
                continue
            if raiz.is_file():
                out.append((raiz, raiz.parent))
                continue
            for dirpath, dirnames, filenames in os.walk(raiz):
                rel = Path(dirpath).relative_to(raiz).parts
                dirnames[:] = [d for d in dirnames if not self._ignorado(rel + (d,), d) and not d.startswith(".")]
                for fn in filenames:
                    p = Path(dirpath) / fn
                    if p.suffix.lower() not in exts or fn.startswith("~$") or self._ignorado(rel, fn):
                        continue
                    try:
                        if p.stat().st_size > max_bytes:
                            continue
                    except OSError:
                        continue
                    out.append((p, raiz))
        return out

    # ------------------------------------------------------------ indexação
    def indexar(self, pastas: Optional[List[Path]] = None, forcar: bool = False,
                progresso: Optional[Callable[[str], None]] = None) -> RelatorioIndexacao:
        progresso = progresso or (lambda s: None)
        rel = RelatorioIndexacao()
        t0 = time.time()
        arquivos = self.varrer(pastas)
        if not arquivos and not self.cfg.biblioteca.pastas and pastas is None:
            raise AgenteErro(
                "Nenhuma pasta configurada na biblioteca. Adicione com:\n"
                "  nlr biblioteca adicionar \"C:\\Users\\voce\\Documentos\\MinhaBiblioteca\""
            )
        emb_id = self.embedder.id if self.embedder else ""
        if emb_id and self._meta("embedder") and self._meta("embedder") != emb_id:
            progresso(f"Modelo de embeddings mudou ({self._meta('embedder')} -> {emb_id}): recalculando vetores.")
            with self._lock:
                self.con.execute("UPDATE trechos SET vetor=NULL")
                self._incrementar_versao()
                self.con.commit()
        vistos = set()
        with self._lock:
            conhecidos = {r[0]: r for r in self.con.execute("SELECT caminho, mtime, tamanho, hash FROM arquivos")}
        for i, (p, raiz) in enumerate(arquivos, start=1):
            chave = str(p.resolve())
            vistos.add(chave)
            st = p.stat()
            antigo = conhecidos.get(chave)
            if antigo and not forcar and antigo[1] == st.st_mtime and antigo[2] == st.st_size:
                rel.inalterados += 1
                continue
            h = _hash(p)
            if antigo and not forcar and antigo[3] == h:
                with self._lock:
                    self.con.execute("UPDATE arquivos SET mtime=?, tamanho=? WHERE caminho=?", (st.st_mtime, st.st_size, chave))
                rel.inalterados += 1
                continue
            progresso(f"[{i}/{len(arquivos)}] Lendo {p.name}")
            try:
                from . import carregadores as _C

                _C.OPCOES.update(ocr=self.cfg.biblioteca.ocr, ocr_idiomas=self.cfg.biblioteca.ocr_idiomas,
                                 tabelas_pdf=self.cfg.biblioteca.tabelas_pdf)
                _C.AVISOS.clear()
                segs = carregar_arquivo(p)
                for _a in _C.AVISOS:
                    progresso("⚠ " + _a)
                    rel.avisos.append(_a)
                trechos = fatiar_segmentos(segs, p.name, self.cfg.biblioteca.tamanho_trecho, self.cfg.biblioteca.sobreposicao)
            except Exception as e:  # noqa: BLE001
                msg = str(e)[:300]
                rel.erros.append((str(p), msg))
                with self._lock:
                    self._remover(chave)
                    self.con.execute("INSERT OR REPLACE INTO arquivos VALUES (?,?,?,?,?,?,?,?,?)",
                                     (chave, str(raiz), st.st_mtime, st.st_size, h, 0, time.time(), msg, ""))
                continue
            vetores = self._embed_docs([t.texto for t in trechos], rel, progresso)
            with self._lock:
                self._remover(chave)
                for ordem, (t, v) in enumerate(zip(trechos, vetores)):
                    cur = self.con.execute(
                        "INSERT INTO trechos (caminho, ordem, local, texto, vetor) VALUES (?,?,?,?,?)",
                        (chave, ordem, t.local, t.texto, None if v is None else np.asarray(v, dtype=np.float32).tobytes()),
                    )
                    self.con.execute("INSERT INTO trechos_fts (rowid, texto, nome) VALUES (?,?,?)",
                                     (cur.lastrowid, t.texto, p.stem.replace("_", " ").replace("-", " ")))
                self.con.execute("INSERT OR REPLACE INTO arquivos VALUES (?,?,?,?,?,?,?,?,?)",
                                 (chave, str(raiz), st.st_mtime, st.st_size, h, len(trechos), time.time(), None,
                                  "; ".join(_C.AVISOS)))
                self._incrementar_versao()
                self.con.commit()
            rel.trechos += len(trechos)
            if antigo:
                rel.atualizados += 1
            else:
                rel.novos += 1
        # remove arquivos que sumiram (só dentro das pastas varridas)
        raizes = {str(r) for _, r in arquivos} | {str(p) for p in (pastas or self.cfg.pastas_biblioteca())}
        with self._lock:
            for (caminho, raiz) in self.con.execute("SELECT caminho, raiz FROM arquivos").fetchall():
                if caminho not in vistos and (raiz in raizes or pastas is None):
                    self._remover(caminho)
                    self.con.execute("DELETE FROM arquivos WHERE caminho=?", (caminho,))
                    rel.removidos += 1
            if emb_id:
                self._set_meta("embedder", emb_id)
            self._incrementar_versao()
            self.con.commit()
        # completa vetores faltantes (ex.: servidor de embeddings estava desligado antes)
        if self.embedder and not rel.aviso_embeddings:
            self.completar_vetores(rel, progresso)
        rel.segundos = time.time() - t0
        return rel

    def _embed_docs(self, textos: List[str], rel: RelatorioIndexacao, progresso) -> List[Optional[List[float]]]:
        if not textos:
            return []
        if not self.embedder:
            return [None] * len(textos)
        if rel.aviso_embeddings:
            rel.sem_vetor += len(textos)
            return [None] * len(textos)
        try:
            return self.embedder.documentos(textos)
        except AgenteErro as e:
            rel.aviso_embeddings = str(e)
            progresso("Aviso: embeddings indisponíveis; indexando só para busca por palavras-chave.")
            rel.sem_vetor += len(textos)
            return [None] * len(textos)

    def completar_vetores(self, rel: Optional[RelatorioIndexacao] = None, progresso=None) -> int:
        progresso = progresso or (lambda s: None)
        if not self.embedder:
            return 0
        with self._lock:
            faltam = self.con.execute("SELECT id, texto FROM trechos WHERE vetor IS NULL").fetchall()
        if not faltam:
            return 0
        progresso(f"Calculando vetores de {len(faltam)} trecho(s)...")
        lote = max(1, self.cfg.biblioteca.lote_embeddings)
        feitos = 0
        for i in range(0, len(faltam), lote):
            parte = faltam[i:i + lote]
            try:
                vets = self.embedder.documentos([t for _, t in parte])
            except AgenteErro as e:
                if rel is not None:
                    rel.aviso_embeddings = str(e)
                break
            with self._lock:
                for (tid, _), v in zip(parte, vets):
                    self.con.execute("UPDATE trechos SET vetor=? WHERE id=?", (np.asarray(v, dtype=np.float32).tobytes(), tid))
                self._incrementar_versao()
                self.con.commit()
            feitos += len(parte)
        if rel is not None:
            rel.sem_vetor = max(0, rel.sem_vetor - feitos)
        return feitos

    def _remover(self, caminho: str) -> None:
        ids = [r[0] for r in self.con.execute("SELECT id FROM trechos WHERE caminho=?", (caminho,))]
        if ids:
            self.con.executemany("DELETE FROM trechos_fts WHERE rowid=?", [(i,) for i in ids])
            self.con.execute("DELETE FROM trechos WHERE caminho=?", (caminho,))

    def limpar(self) -> None:
        with self._lock:
            self.con.executescript("DELETE FROM trechos; DELETE FROM trechos_fts; DELETE FROM arquivos; DELETE FROM meta;")
            self.con.commit()

    # ------------------------------------------------------------ busca
    def buscar_bm25(self, consulta: str, k: int = 50) -> List[Tuple[int, float]]:
        q = _consulta_fts(consulta)
        if not q:
            return []
        with self._lock:
            try:
                rows = self.con.execute(
                    "SELECT rowid, bm25(trechos_fts, 1.0, 2.0) FROM trechos_fts WHERE trechos_fts MATCH ? "
                    "ORDER BY bm25(trechos_fts, 1.0, 2.0) LIMIT ?", (q, k)).fetchall()
            except sqlite3.OperationalError as e:
                log.warning("Consulta FTS falhou (%s): %s", q, e)
                return []
        return [(int(r[0]), -float(r[1])) for r in rows]

    def _matriz(self) -> Tuple[np.ndarray, np.ndarray]:
        v = self._versao()
        if self._cache_vet and self._cache_vet[0] == v:
            return self._cache_vet[1], self._cache_vet[2]
        with self._lock:
            rows = self.con.execute("SELECT id, vetor FROM trechos WHERE vetor IS NOT NULL").fetchall()
        if not rows:
            ids, mat = np.zeros(0, dtype=np.int64), np.zeros((0, 1), dtype=np.float32)
        else:
            ids = np.array([r[0] for r in rows], dtype=np.int64)
            dim = len(rows[0][1]) // 4
            mat = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows if len(r[1]) // 4 == dim])
            if mat.shape[0] != len(ids):
                ids = np.array([r[0] for r in rows if len(r[1]) // 4 == dim], dtype=np.int64)
            norm = np.linalg.norm(mat, axis=1, keepdims=True)
            norm[norm == 0] = 1.0
            mat = mat / norm
        self._cache_vet = (v, ids, mat)
        return ids, mat

    def buscar_vetor(self, consulta: str, k: int = 50) -> List[Tuple[int, float]]:
        if not self.embedder:
            return []
        ids, mat = self._matriz()
        if len(ids) == 0:
            return []
        try:
            q = np.asarray(self.embedder.consulta(consulta), dtype=np.float32)
        except AgenteErro as e:
            log.warning("Embeddings indisponíveis na busca: %s", e)
            return []
        if q.shape[0] != mat.shape[1]:
            log.warning("Dimensão do vetor da consulta difere do índice: reindexe com `nlr indexar --forcar`.")
            return []
        q = q / (np.linalg.norm(q) or 1.0)
        sims = mat @ q
        top = np.argsort(-sims)[:k]
        return [(int(ids[i]), float(sims[i])) for i in top]

    def trechos_por_id(self, ids: List[int]) -> dict:
        if not ids:
            return {}
        with self._lock:
            rows = self.con.execute(
                f"SELECT t.id, t.caminho, t.local, t.texto, a.raiz FROM trechos t LEFT JOIN arquivos a "
                f"ON a.caminho=t.caminho WHERE t.id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return {r[0]: r for r in rows}

    # ------------------------------------------------------------ status
    def status(self) -> dict:
        with self._lock:
            n_arq = self.con.execute("SELECT COUNT(*) FROM arquivos WHERE erro IS NULL").fetchone()[0]
            n_err = self.con.execute("SELECT COUNT(*) FROM arquivos WHERE erro IS NOT NULL").fetchone()[0]
            n_tr = self.con.execute("SELECT COUNT(*) FROM trechos").fetchone()[0]
            n_vet = self.con.execute("SELECT COUNT(*) FROM trechos WHERE vetor IS NOT NULL").fetchone()[0]
            erros = self.con.execute("SELECT caminho, erro FROM arquivos WHERE erro IS NOT NULL LIMIT 20").fetchall()
        return {"arquivos": n_arq, "arquivos_com_erro": n_err, "trechos": n_tr, "trechos_com_vetor": n_vet,
                "embedder": self._meta("embedder") or "(nenhum)", "erros": erros, "db": str(self.db_path)}

    def arquivos(self, n: int = 500) -> List[dict]:
        """Arquivos indexados com nº de trechos, tabelas, páginas OCR e avisos (para a página Documentos)."""
        with self._lock:
            rows = self.con.execute("SELECT caminho, n_trechos, indexado_em, erro, avisos, tamanho FROM arquivos "
                                    "ORDER BY indexado_em DESC LIMIT ?", (n,)).fetchall()
            out = []
            for c, nt, em, erro, av, tam in rows:
                tab = self.con.execute("SELECT COUNT(*) FROM trechos WHERE caminho=? AND (local LIKE '%tabela%' "
                                       "OR texto LIKE '%|---|%')", (c,)).fetchone()[0]
                ocr = self.con.execute("SELECT COUNT(DISTINCT local) FROM trechos WHERE caminho=? AND local LIKE '%(OCR)%'",
                                       (c,)).fetchone()[0]
                out.append({"caminho": c, "nome": Path(c).name, "trechos": nt, "indexado_em": em, "erro": erro,
                            "avisos": av or "", "tabelas": tab, "paginas_ocr": ocr, "tamanho": tam})
        return out

    def fechar(self) -> None:
        try:
            self.con.close()
        except Exception:  # noqa: BLE001
            pass
