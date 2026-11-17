"""Memória persistente em SQLite (dados/agente.db).

Camadas:
  * curto prazo  — histórico de cada sessão de chat (tabela mensagens), resumido quando fica grande;
  * longo prazo  — lembranças (fatos, preferências, decisões, lições) com escopo 'global' ou 'projeto:<id>',
                   recuperadas por busca híbrida (palavras-chave FTS5 + vetores, quando houver embeddings);
  * por projeto  — além das lembranças com escopo do projeto, cada projeto tem DIARIO.md e tarefas.json
                   na própria pasta (veja agentes/projeto.py).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from ..config import Config
from ..erros import AgenteErro
from ..textutil import rrf, tokenizar

log = logging.getLogger(__name__)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS sessoes (id TEXT PRIMARY KEY, titulo TEXT, criada REAL, atualizada REAL, resumo TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS mensagens (id INTEGER PRIMARY KEY AUTOINCREMENT, sessao TEXT, papel TEXT, conteudo TEXT, criada REAL);
CREATE INDEX IF NOT EXISTS ix_msg_sessao ON mensagens(sessao);
CREATE TABLE IF NOT EXISTS lembrancas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, escopo TEXT, tipo TEXT, texto TEXT, origem TEXT, criada REAL, vetor BLOB
);
CREATE VIRTUAL TABLE IF NOT EXISTS lembrancas_fts USING fts5(texto, tokenize='unicode61 remove_diacritics 2');
"""


@dataclass
class Lembranca:
    id: int
    escopo: str
    tipo: str
    texto: str
    origem: str
    criada: float
    marca: str = "inferido"  # usuario (literal) | inferido | inhearsay  (coerente com nucleo/inhearsay.py)
    evidencia: str = ""  # trecho literal do usuário que apoia o fato
    usos: int = 0
    atualizada: float = 0.0
    fixada: int = 0

    def dict(self) -> dict:
        return dict(self.__dict__)

    def rotulo(self) -> str:
        return {"usuario": "[usuário: literal]", "inhearsay": "[⚠ inhearsay]"}.get(self.marca, "[inferido]")


_COLS = "id, escopo, tipo, texto, origem, criada, marca, evidencia, usos, atualizada, fixada"
MARCAS = ("usuario", "inferido", "inhearsay")


_LITERAL = None


def fatos_literais(msgs_usuario: List[str]) -> List[Tuple[str, str]]:
    """Frases do PRÓPRIO usuário em 1ª pessoa que declaram fato/preferência/decisão (sem modelo; funciona com
    modelos pequenos). Devolve [(frase, tipo)]. Frases condicionais ("se...", "talvez") ficam de fora."""
    import re

    global _LITERAL
    if _LITERAL is None:
        _LITERAL = [
            (re.compile(r"\b(prefiro|gosto de|n[aã]o gosto|odeio|quero que|sempre (uso|use)|i prefer|i like|i (always )?want)\b", re.I), "preferencia"),
            (re.compile(r"\b(decidi|vamos usar|vou usar|escolhi|i decided|we will use)\b", re.I), "decisao"),
            (re.compile(r"\b(meu nome [eé]|me chamo|eu sou|sou (um|uma|o|a)\b|trabalho (com|na|no|em)|moro em|estou (criando|fazendo|desenvolvendo|trabalhando)|"
                        r"eu uso|uso o|meu (projeto|jogo|computador|pc)|minha (empresa|equipe|placa)|my name is|i am|i'm (building|making|working)|i use)\b", re.I), "fato"),
        ]
    cond = re.compile(r"^\s*(se|caso|talvez|quem sabe|if|maybe)\b|\b(talvez|maybe)\b", re.I)
    out: List[Tuple[str, str]] = []
    for m in msgs_usuario:
        for frase in re.split(r"(?<=[.!?])\s+|\n+", m or ""):
            f = frase.strip()
            if not (8 <= len(f) <= 240) or f.endswith("?") or cond.search(f):
                continue
            for rx, tipo in _LITERAL:
                if rx.search(f):
                    out.append((f, tipo))
                    break
    return out


def classificar(texto: str, msgs_usuario: Optional[List[str]]) -> Tuple[str, str]:
    """(marca, evidência) de um fato, usando o mesmo verificador do handoff (sem modelo)."""
    if not msgs_usuario:
        return "inferido", ""
    from ..nucleo import inhearsay

    v = inhearsay.verificar(texto, msgs_usuario)
    it = v.itens[0] if v.itens else None
    apoio, msg = inhearsay._melhor_apoio(texto, msgs_usuario)
    if it is None:
        return "inferido", ""
    if it.origem == "inhearsay":
        return "inhearsay", it.motivo
    if it.origem == "usuario" or apoio >= 0.6:
        return "usuario", msg[:240]
    return "inferido", ""


class ItemExtraido(BaseModel):
    texto: str = Field(description="fato curto e autocontido, em português")
    tipo: Literal["fato", "preferencia", "decisao", "licao"] = "fato"


class Extracao(BaseModel):
    lembrancas: List[ItemExtraido] = Field(default_factory=list)


def _parecido(a: str, b: str) -> bool:
    import re

    if set(re.findall(r"\d+", a)) != set(re.findall(r"\d+", b)):
        return False  # "custa 10" e "custa 20" são fatos diferentes
    ta, tb = set(tokenizar(a)), set(tokenizar(b))
    if not ta or not tb:
        return a.strip().lower() == b.strip().lower()
    inter = len(ta & tb)
    # mesmo conjunto (>=80%) ou um contido no outro (ex.: "prefere tema escuro" x "o usuário prefere tema escuro")
    return inter / len(ta | tb) >= 0.8 or (min(len(ta), len(tb)) >= 3 and inter / min(len(ta), len(tb)) >= 0.9)


class Memoria:
    def __init__(self, cfg: Config, embedder=None, db: Optional[Path] = None):
        self.cfg = cfg
        self.embedder = embedder
        self._lock = threading.RLock()
        self.con = sqlite3.connect(str(db or cfg.db_principal), check_same_thread=False)
        self.con.executescript(ESQUEMA)
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(sessoes)")}
        if "pai" not in cols:  # migração NLR 0.3: chats ligados (handoff automático)
            self.con.execute("ALTER TABLE sessoes ADD COLUMN pai TEXT DEFAULT ''")
        if "projeto" not in cols:  # migração NLR 0.5: chat ligado a um projeto (memória de longo prazo)
            self.con.execute("ALTER TABLE sessoes ADD COLUMN projeto TEXT DEFAULT ''")
        lc = {r[1] for r in self.con.execute("PRAGMA table_info(lembrancas)")}
        for col, tipo in (("marca", "TEXT DEFAULT 'inferido'"), ("evidencia", "TEXT DEFAULT ''"),
                          ("usos", "INTEGER DEFAULT 0"), ("atualizada", "REAL DEFAULT 0"), ("fixada", "INTEGER DEFAULT 0")):
            if col not in lc:
                self.con.execute(f"ALTER TABLE lembrancas ADD COLUMN {col} {tipo}")
        self.con.execute("UPDATE lembrancas SET marca='usuario' WHERE origem='usuario' AND marca='inferido' AND usos=0 "
                         "AND atualizada=0")
        self.con.execute("UPDATE lembrancas SET atualizada=criada WHERE atualizada=0")
        self.con.commit()

    # ------------------------------------------------------------ sessões (curto prazo)
    def nova_sessao(self, titulo: str = "", pai: str = "") -> str:
        sid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        with self._lock:
            proj = ""
            if pai:  # continuação (handoff) herda o projeto da memória
                r = self.con.execute("SELECT projeto FROM sessoes WHERE id=?", (pai,)).fetchone()
                proj = (r[0] or "") if r else ""
            self.con.execute("INSERT INTO sessoes (id, titulo, criada, atualizada, resumo, pai, projeto) VALUES (?,?,?,?,?,?,?)",
                             (sid, titulo or "conversa", time.time(), time.time(), "", pai or "", proj))
            self.con.commit()
        return sid

    def titulo_sessao(self, sid: str) -> str:
        with self._lock:
            r = self.con.execute("SELECT titulo FROM sessoes WHERE id=?", (sid,)).fetchone()
        return r[0] if r else ""

    def pai_sessao(self, sid: str) -> str:
        with self._lock:
            r = self.con.execute("SELECT pai FROM sessoes WHERE id=?", (sid,)).fetchone()
        return r[0] if r and r[0] else ""

    def cadeia_sessoes(self, sid: str) -> List[str]:
        """Do chat mais antigo ao atual (segue os links de handoff)."""
        cadeia, atual = [], sid
        while atual and atual not in cadeia:
            cadeia.append(atual)
            atual = self.pai_sessao(atual)
        return list(reversed(cadeia))

    def renomear_sessao(self, sid: str, titulo: str) -> None:
        with self._lock:
            self.con.execute("UPDATE sessoes SET titulo=? WHERE id=?", (titulo[:120], sid))
            self.con.commit()

    def apagar_sessao(self, sid: str) -> None:
        with self._lock:
            self.con.execute("DELETE FROM mensagens WHERE sessao=?", (sid,))
            self.con.execute("UPDATE sessoes SET pai='' WHERE pai=?", (sid,))
            self.con.execute("DELETE FROM sessoes WHERE id=?", (sid,))
            self.con.commit()

    def buscar_sessoes(self, termo: str, n: int = 50) -> List[str]:
        like = f"%{termo}%"
        with self._lock:
            rows = self.con.execute(
                "SELECT DISTINCT s.id FROM sessoes s LEFT JOIN mensagens m ON m.sessao=s.id "
                "WHERE s.titulo LIKE ? OR m.conteudo LIKE ? ORDER BY s.atualizada DESC LIMIT ?", (like, like, n)).fetchall()
        return [r[0] for r in rows]

    def filho_sessao(self, sid: str) -> str:
        with self._lock:
            r = self.con.execute("SELECT id FROM sessoes WHERE pai=? ORDER BY criada DESC LIMIT 1", (sid,)).fetchone()
        return r[0] if r else ""

    def sessao_existe(self, sid: str) -> bool:
        with self._lock:
            return self.con.execute("SELECT 1 FROM sessoes WHERE id=?", (sid,)).fetchone() is not None

    def ultima_sessao(self) -> Optional[str]:
        with self._lock:
            r = self.con.execute("SELECT id FROM sessoes ORDER BY atualizada DESC LIMIT 1").fetchone()
        return r[0] if r else None

    def listar_sessoes(self, n: int = 20) -> List[tuple]:
        with self._lock:
            return self.con.execute(
                "SELECT s.id, s.titulo, s.atualizada, (SELECT COUNT(*) FROM mensagens m WHERE m.sessao=s.id) "
                "FROM sessoes s ORDER BY atualizada DESC LIMIT ?", (n,)).fetchall()

    def adicionar_mensagem(self, sid: str, papel: str, conteudo: str) -> None:
        with self._lock:
            self.con.execute("INSERT INTO mensagens (sessao, papel, conteudo, criada) VALUES (?,?,?,?)",
                             (sid, papel, conteudo, time.time()))
            if papel == "user":
                self.con.execute("UPDATE sessoes SET titulo=? WHERE id=? AND titulo='conversa'", (conteudo[:60], sid))
            self.con.execute("UPDATE sessoes SET atualizada=? WHERE id=?", (time.time(), sid))
            self.con.commit()

    def historico(self, sid: str, n: Optional[int] = None) -> List[dict]:
        n = n or self.cfg.memoria.max_mensagens_historico
        with self._lock:
            rows = self.con.execute("SELECT papel, conteudo FROM mensagens WHERE sessao=? ORDER BY id DESC LIMIT ?",
                                    (sid, n)).fetchall()
        return [{"role": p, "content": c} for p, c in reversed(rows)]

    def resumo_sessao(self, sid: str) -> str:
        with self._lock:
            r = self.con.execute("SELECT resumo FROM sessoes WHERE id=?", (sid,)).fetchone()
        return r[0] if r and r[0] else ""

    def salvar_resumo(self, sid: str, resumo: str) -> None:
        with self._lock:
            self.con.execute("UPDATE sessoes SET resumo=? WHERE id=?", (resumo, sid))
            self.con.commit()

    def total_mensagens(self, sid: str) -> int:
        with self._lock:
            return self.con.execute("SELECT COUNT(*) FROM mensagens WHERE sessao=?", (sid,)).fetchone()[0]

    # ------------------------------------------------------------ lembranças (longo prazo)
    def _vetor(self, texto: str, consulta: bool = False):
        if not self.embedder:
            return None
        try:
            v = self.embedder.consulta(texto) if consulta else self.embedder.documentos([texto])[0]
            return np.asarray(v, dtype=np.float32)
        except AgenteErro as e:
            log.info("Sem embeddings para a memória: %s", e)
            return None

    def lembrar(self, texto: str, tipo: str = "fato", escopo: str = "global", origem: str = "",
                marca: Optional[str] = None, evidencia: str = "") -> Optional[int]:
        """Salva um fato com MARCA DE ORIGEM. Deduplica: se já existe parecido no escopo, reforça (usos+1) e,
        se o novo for literal do usuário, promove a marca. Escrito pelo próprio usuário => 'usuario'."""
        texto = " ".join((texto or "").split())
        if len(texto) < 3:
            return None
        if marca is None:
            marca = "usuario" if origem == "usuario" else "inferido"
        if marca not in MARCAS:
            marca = "inferido"
        agora = time.time()
        with self._lock:
            existentes = self.con.execute("SELECT id, texto, marca FROM lembrancas WHERE escopo=?", (escopo,)).fetchall()
        for lid, t, m in existentes:
            if _parecido(t, texto):
                with self._lock:
                    nova = marca if (marca == "usuario" or m == "inhearsay") else m
                    self.con.execute("UPDATE lembrancas SET usos=usos+1, atualizada=?, marca=?, "
                                     "evidencia=CASE WHEN ?<>'' THEN ? ELSE evidencia END WHERE id=?",
                                     (agora, nova, evidencia, evidencia, lid))
                    self.con.commit()
                return lid  # já sabia disso
        v = self._vetor(texto)
        if v is not None and existentes:  # dedup semântica (mesmo fato com outras palavras)
            with self._lock:
                rows = self.con.execute("SELECT id, vetor FROM lembrancas WHERE escopo=? AND vetor IS NOT NULL",
                                        (escopo,)).fetchall()
            for lid, blob in rows:
                w = np.frombuffer(blob, dtype=np.float32)
                if w.shape == v.shape and float(w @ v / ((np.linalg.norm(w) * np.linalg.norm(v)) + 1e-9)) > 0.95:
                    with self._lock:
                        self.con.execute("UPDATE lembrancas SET usos=usos+1, atualizada=? WHERE id=?", (agora, lid))
                        self.con.commit()
                    return lid
        with self._lock:
            cur = self.con.execute(
                "INSERT INTO lembrancas (escopo, tipo, texto, origem, criada, vetor, marca, evidencia, usos, atualizada, fixada)"
                " VALUES (?,?,?,?,?,?,?,?,0,?,0)",
                (escopo, tipo, texto, origem, agora, None if v is None else v.tobytes(), marca, evidencia, agora))
            self.con.execute("INSERT INTO lembrancas_fts (rowid, texto) VALUES (?,?)", (cur.lastrowid, texto))
            self.con.commit()
            return cur.lastrowid

    def obter(self, lid: int) -> Optional[Lembranca]:
        with self._lock:
            r = self.con.execute(f"SELECT {_COLS} FROM lembrancas WHERE id=?", (lid,)).fetchone()
        return Lembranca(*r) if r else None

    def atualizar(self, lid: int, texto: Optional[str] = None, escopo: Optional[str] = None, tipo: Optional[str] = None,
                  marca: Optional[str] = None, fixada: Optional[bool] = None) -> Optional[Lembranca]:
        """Edição pelo usuário (UI/CLI). Editar o texto torna o fato 'usuario' (ele escreveu)."""
        atual = self.obter(lid)
        if not atual:
            return None
        with self._lock:
            if texto is not None and " ".join(texto.split()) != atual.texto:
                texto = " ".join(texto.split())
                v = self._vetor(texto)
                self.con.execute("UPDATE lembrancas SET texto=?, vetor=?, marca='usuario', origem='usuario', "
                                 "evidencia='editado pelo usuário' WHERE id=?",
                                 (texto, None if v is None else v.tobytes(), lid))
                self.con.execute("DELETE FROM lembrancas_fts WHERE rowid=?", (lid,))
                self.con.execute("INSERT INTO lembrancas_fts (rowid, texto) VALUES (?,?)", (lid, texto))
            if escopo:
                self.con.execute("UPDATE lembrancas SET escopo=? WHERE id=?", (escopo, lid))
            if tipo:
                self.con.execute("UPDATE lembrancas SET tipo=? WHERE id=?", (tipo, lid))
            if marca in MARCAS:
                self.con.execute("UPDATE lembrancas SET marca=? WHERE id=?", (marca, lid))
            if fixada is not None:
                self.con.execute("UPDATE lembrancas SET fixada=? WHERE id=?", (1 if fixada else 0, lid))
            self.con.execute("UPDATE lembrancas SET atualizada=? WHERE id=?", (time.time(), lid))
            self.con.commit()
        return self.obter(lid)

    def esquecer(self, lid: int) -> bool:
        with self._lock:
            n = self.con.execute("DELETE FROM lembrancas WHERE id=?", (lid,)).rowcount
            self.con.execute("DELETE FROM lembrancas_fts WHERE rowid=?", (lid,))
            self.con.commit()
        return n > 0

    def esquecer_antigos(self, escopo: Optional[str] = None, dias: Optional[float] = None,
                         max_por_escopo: Optional[int] = None, agora: Optional[float] = None) -> List[int]:
        """Esquecimento: apaga fatos INFERIDOS/inhearsay não usados há `dias` (inhearsay: na metade do prazo) e
        corta o excesso por escopo (mantém fixados, literais do usuário e os mais usados/recentes).
        Fatos literais do usuário e fixados nunca são esquecidos automaticamente."""
        mc = self.cfg.memoria
        dias = mc.dias_para_esquecer if dias is None else dias
        max_por_escopo = mc.max_por_escopo if max_por_escopo is None else max_por_escopo
        agora = agora or time.time()
        apagar: List[int] = []
        with self._lock:
            sql = f"SELECT {_COLS} FROM lembrancas" + (" WHERE escopo=?" if escopo else "")
            todas = [Lembranca(*r) for r in self.con.execute(sql, (escopo,) if escopo else ())]
        protegidas = lambda x: x.fixada or x.marca == "usuario"  # noqa: E731
        for x in todas:
            if protegidas(x) or dias <= 0:
                continue
            prazo = dias * 86400 * (0.5 if x.marca == "inhearsay" else 1.0) * (1 + min(x.usos, 5))
            if agora - (x.atualizada or x.criada) > prazo:
                apagar.append(x.id)
        if max_por_escopo:
            por: Dict[str, List[Lembranca]] = {}
            for x in todas:
                if x.id not in apagar:
                    por.setdefault(x.escopo, []).append(x)
            for lst in por.values():
                livres = sorted([x for x in lst if not protegidas(x)], key=lambda x: (x.usos, x.atualizada))
                excesso = len(lst) - max_por_escopo
                apagar += [x.id for x in livres[:max(0, excesso)]]
        for lid in apagar:
            self.esquecer(lid)
        return apagar

    def escopos(self) -> List[tuple]:
        with self._lock:
            return self.con.execute("SELECT escopo, COUNT(*) FROM lembrancas GROUP BY escopo ORDER BY escopo").fetchall()

    def listar(self, escopo: Optional[str] = None, n: int = 200, busca: str = "") -> List[Lembranca]:
        sql = f"SELECT {_COLS} FROM lembrancas"
        cond, args = [], []
        if escopo:
            cond.append("escopo=?")
            args.append(escopo)
        if busca:
            cond.append("texto LIKE ?")
            args.append(f"%{busca}%")
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY fixada DESC, id DESC LIMIT ?"
        with self._lock:
            rows = self.con.execute(sql, tuple(args) + (n,)).fetchall()
        return [Lembranca(*r) for r in rows]

    # projeto do chat (escopo da memória de longo prazo)
    def definir_projeto_sessao(self, sid: str, projeto: str) -> None:
        with self._lock:
            self.con.execute("UPDATE sessoes SET projeto=? WHERE id=?", ((projeto or "").strip(), sid))
            self.con.commit()

    def projeto_sessao(self, sid: str) -> str:
        with self._lock:
            r = self.con.execute("SELECT projeto FROM sessoes WHERE id=?", (sid,)).fetchone()
        return (r[0] or "") if r else ""

    def recordar(self, consulta: str, escopos: Optional[List[str]] = None, k: Optional[int] = None) -> List[Lembranca]:
        """Lembranças mais relevantes para a consulta (escopos: ex. ['global', 'projeto:abc'])."""
        k = k or self.cfg.memoria.max_lembrancas_no_contexto
        escopos = escopos or ["global"]
        marc = ",".join("?" * len(escopos))
        with self._lock:
            todas = self.con.execute(
                f"SELECT id, escopo, tipo, texto, origem, criada, marca, evidencia, usos, atualizada, fixada, vetor "
                f"FROM lembrancas WHERE escopo IN ({marc}) AND marca<>'inhearsay'", escopos).fetchall()
        if not todas:
            return []
        por_id = {r[0]: r for r in todas}
        listas = []
        toks = tokenizar(consulta)
        if toks:
            q = " OR ".join(f'"{t}"' for t in toks[:24])
            with self._lock:
                try:
                    rows = self.con.execute(
                        "SELECT rowid FROM lembrancas_fts WHERE lembrancas_fts MATCH ? ORDER BY rank LIMIT 50", (q,)).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            listas.append([r[0] for r in rows if r[0] in por_id])
        com_vetor = [r for r in todas if r[11]]
        if com_vetor:
            qv = self._vetor(consulta, consulta=True)
            if qv is not None:
                dim = qv.shape[0]
                cand = [r for r in com_vetor if len(r[11]) // 4 == dim]
                if cand:
                    mat = np.vstack([np.frombuffer(r[11], dtype=np.float32) for r in cand])
                    mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
                    sims = mat @ (qv / (np.linalg.norm(qv) + 1e-9))
                    ordem = np.argsort(-sims)
                    listas.append([cand[i][0] for i in ordem if sims[i] > 0.25][:50])
        listas.append([r[0] for r in todas if r[10]])  # fixadas ganham um empurrão
        fus = rrf(listas)
        ids = sorted(fus, key=lambda i: -fus[i])[:k]
        if ids:
            with self._lock:
                self.con.execute(f"UPDATE lembrancas SET usos=usos+1, atualizada=? WHERE id IN ({','.join('?' * len(ids))})",
                                 [time.time()] + ids)
                self.con.commit()
        return [Lembranca(*por_id[i][:11]) for i in ids]

    # ------------------------------------------------------------ extração automática
    def extrair(self, llm, texto: str, escopo: str = "global", origem: str = "",
                msgs_usuario: Optional[List[str]] = None) -> List[int]:
        """Pede ao modelo fatos duráveis (preferências do usuário, decisões, lições) e os salva."""
        from ..prompts import PROMPT_EXTRAIR_MEMORIA

        ids: List[int] = []
        for frase, tipo in fatos_literais(msgs_usuario or []):  # literais primeiro (determinístico)
            lid = self.lembrar(frase, tipo, escopo, origem, marca="usuario", evidencia=frase[:240])
            if lid:
                ids.append(lid)
        try:
            r = llm.chat_json(
                [{"role": "system", "content": PROMPT_EXTRAIR_MEMORIA},
                 {"role": "user", "content": texto[-6000:]}],
                Extracao, max_tokens=600, tentativas=2)
        except AgenteErro as e:
            log.info("Extração de memória ignorada: %s", e)
            return ids
        for item in r.lembrancas[:5]:
            marca, evid = classificar(item.texto, msgs_usuario)
            from ..nucleo.inhearsay import CONDICAO

            if item.tipo == "decisao" and CONDICAO.search(item.texto):
                item.tipo = "fato"  # condicional não é decisão (coerente com o guard de inhearsay)
            lid = self.lembrar(item.texto, item.tipo, escopo, origem, marca=marca, evidencia=evid)
            if lid:
                ids.append(lid)
        return ids

    def fechar(self) -> None:
        try:
            self.con.close()
        except Exception:  # noqa: BLE001
            pass
