"""Arquivos de estado de cada projeto (legíveis por humanos e usados para retomar).

<pasta do projeto>/
    PLANO.md        plano atual com o status de cada tarefa
    DIARIO.md       diário cronológico (o que foi feito, comandos, revisões)
    PESQUISA.md     pesquisa inicial (biblioteca + web) com fontes
    RELATORIO.md    relatório final
    .agente/projeto.json   metadados (objetivo, status, fase)
    .agente/tarefas.json   tarefas estruturadas (fonte da verdade para retomar)
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from ..config import Config
from ..erros import AgenteErro

STATUS_ICONE = {"pendente": "[ ]", "em_andamento": "[~]", "concluida": "[x]", "com_ressalvas": "[!]", "falhou": "[F]"}


def slug(texto: str, n: int = 40) -> str:
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return (t[:n].rstrip("-") or "projeto")


@dataclass
class InfoProjeto:
    id: str
    nome: str
    objetivo: str
    pasta: str
    status: str = "novo"  # novo | em_andamento | interrompido | concluido | falhou
    fase: str = ""
    criado: float = field(default_factory=time.time)
    atualizado: float = field(default_factory=time.time)
    erro: str = ""
    thread: str = ""  # id do fluxo no checkpointer (muda a cada "continuar")


class ProjetoStore:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def criar(self, objetivo: str, nome: Optional[str] = None) -> InfoProjeto:
        base = slug(nome or objetivo)
        pid = f"{time.strftime('%Y%m%d')}-{base}"
        pasta = self.cfg.dir_projetos / pid
        i = 2
        while pasta.exists():
            pasta = self.cfg.dir_projetos / f"{pid}-{i}"
            i += 1
        pid = pasta.name
        (pasta / ".agente").mkdir(parents=True)
        info = InfoProjeto(id=pid, nome=nome or objetivo[:60], objetivo=objetivo, pasta=str(pasta))
        self.salvar_info(info)
        self.diario(info, f"Projeto criado. Objetivo: {objetivo}")
        return info

    def pasta(self, pid: str) -> Path:
        return self.cfg.dir_projetos / pid

    def carregar(self, pid: str) -> InfoProjeto:
        arq = self.pasta(pid) / ".agente" / "projeto.json"
        if not arq.exists():
            candidatos = [p.name for p in self.cfg.dir_projetos.iterdir() if p.is_dir() and pid in p.name]
            if len(candidatos) == 1:
                return self.carregar(candidatos[0])
            raise AgenteErro(f"Projeto '{pid}' não encontrado. Veja a lista com: nlr projeto listar")
        return InfoProjeto(**json.loads(arq.read_text(encoding="utf-8")))

    def salvar_info(self, info: InfoProjeto) -> None:
        info.atualizado = time.time()
        arq = Path(info.pasta) / ".agente" / "projeto.json"
        arq.write_text(json.dumps(asdict(info), ensure_ascii=False, indent=2), encoding="utf-8")

    def listar(self) -> List[InfoProjeto]:
        out = []
        for p in sorted(self.cfg.dir_projetos.glob("*/.agente/projeto.json")):
            try:
                out.append(InfoProjeto(**json.loads(p.read_text(encoding="utf-8"))))
            except Exception:  # noqa: BLE001
                continue
        return sorted(out, key=lambda x: -x.atualizado)

    # ------------------------------------------------------------ tarefas
    def salvar_tarefas(self, info: InfoProjeto, tarefas: List[dict], resumo_plano: str = "") -> None:
        pasta = Path(info.pasta)
        (pasta / ".agente" / "tarefas.json").write_text(
            json.dumps({"resumo": resumo_plano, "tarefas": tarefas}, ensure_ascii=False, indent=2), encoding="utf-8")
        linhas = [f"# Plano — {info.nome}", "", f"**Objetivo:** {info.objetivo}", ""]
        if resumo_plano:
            linhas += [resumo_plano, ""]
        linhas.append("Legenda: [ ] pendente · [~] em andamento · [x] concluída · [!] concluída com ressalvas · [F] falhou")
        linhas.append("")
        for t in tarefas:
            linhas.append(f"{STATUS_ICONE.get(t['status'], '[?]')} **{t['id']}. {t['titulo']}** ({t['tipo']})")
            linhas.append(f"    {t['descricao']}")
            if t.get("criterios"):
                linhas.append("    Critérios: " + "; ".join(t["criterios"]))
            if t.get("depende_de"):
                linhas.append("    Depende de: " + ", ".join(str(d) for d in t["depende_de"]))
            if t.get("feedback") and t["status"] != "concluida":
                linhas.append(f"    Revisão: {t['feedback'][:300]}")
            linhas.append("")
        (pasta / "PLANO.md").write_text("\n".join(linhas), encoding="utf-8")

    def carregar_tarefas(self, info: InfoProjeto) -> tuple:
        arq = Path(info.pasta) / ".agente" / "tarefas.json"
        if not arq.exists():
            return "", []
        d = json.loads(arq.read_text(encoding="utf-8"))
        return d.get("resumo", ""), d.get("tarefas", [])

    def diario(self, info: InfoProjeto, texto: str) -> None:
        arq = Path(info.pasta) / "DIARIO.md"
        novo = not arq.exists()
        with arq.open("a", encoding="utf-8") as f:
            if novo:
                f.write(f"# Diário — {info.nome}\n\n")
            f.write(f"- **{time.strftime('%Y-%m-%d %H:%M:%S')}** — {texto}\n")
