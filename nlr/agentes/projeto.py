"""Agente de projetos: grafo LangGraph com checkpoints em SQLite (retoma de onde parou).

    START -> pesquisar -> planejar -> executar <-> revisar
                                         |
                                         v
                                     finalizar -> END

* pesquisar: pesquisa profunda (biblioteca + web) sobre o objetivo -> PESQUISA.md
* planejar : Planejador gera tarefas (JSON validado) -> PLANO.md e .agente/tarefas.json
* executar : escolhe a próxima tarefa pendente e chama o sub-agente do tipo certo
             (pesquisador, desenvolvedor, redator) num laço com ferramentas
* revisar  : verificações determinísticas (sintaxe Python, pytest) + Revisor (JSON) -> aprova ou devolve
* finalizar: RELATORIO.md + lições para a memória de longo prazo
Cada nó concluído gera um checkpoint (dados/checkpoints.db, thread = id do projeto).
"""
from __future__ import annotations

import logging
import py_compile
import sqlite3
import time
from pathlib import Path
from typing import Callable, List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field

from ..erros import AgenteErro, PermissaoNegada, SaidaInvalida
from ..ferramentas.comandos import rodar
from ..prompts import PAPEIS, PROMPT_PLANEJADOR, PROMPT_RELATORIO, PROMPT_REVISOR
from .pesquisa import pesquisar, relatorio_markdown
from .projeto_store import InfoProjeto, ProjetoStore
from .react import AgenteReact

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ schemas
class TarefaPlano(BaseModel):
    titulo: str = Field(description="título curto")
    descricao: str = Field(description="o que fazer, de forma concreta")
    tipo: Literal["pesquisa", "codigo", "teste", "docs", "comando"] = "codigo"
    criterios_aceite: List[str] = Field(default_factory=list, description="como verificar que ficou pronto")
    depende_de: List[int] = Field(default_factory=list, description="números (1, 2...) das tarefas anteriores necessárias")


class Plano(BaseModel):
    resumo: str = Field(description="visão geral do plano em 1-3 frases")
    tarefas: List[TarefaPlano] = Field(min_length=1)


class Revisao(BaseModel):
    aprovado: bool
    problemas: List[str] = Field(default_factory=list)
    sugestoes: str = ""


class EstadoProjeto(TypedDict, total=False):
    projeto_id: str
    objetivo: str
    pesquisa: str
    resumo_plano: str
    tarefas: List[dict]
    atual: Optional[int]
    ultimo_resultado: dict
    fase: str
    relatorio: str


PAPEL_POR_TIPO = {"pesquisa": "pesquisador", "codigo": "desenvolvedor", "teste": "desenvolvedor",
                  "comando": "desenvolvedor", "docs": "redator"}
GRUPOS_POR_PAPEL = {"pesquisador": ["pesquisa", "arquivos", "memoria", "mcp", "util", "pixel", "abnt"],
                    "desenvolvedor": ["arquivos", "codigo", "memoria", "mcp", "util", "pixel"],
                    "redator": ["arquivos", "pesquisa", "memoria", "util", "abnt"]}


def plano_padrao(objetivo: str) -> Plano:
    """Plano determinístico usado quando o modelo não consegue gerar um plano válido."""
    return Plano(resumo="Plano padrão (o modelo não gerou um plano válido).", tarefas=[
        TarefaPlano(titulo="Entender e detalhar o objetivo", tipo="pesquisa",
                    descricao=f"Levante requisitos e informações para: {objetivo}. Salve em NOTAS.md.",
                    criterios_aceite=["NOTAS.md existe"]),
        TarefaPlano(titulo="Implementar a solução", tipo="codigo", descricao=f"Implemente: {objetivo}",
                    criterios_aceite=["arquivos principais criados"], depende_de=[1]),
        TarefaPlano(titulo="Testar", tipo="teste", descricao="Crie testes automatizados e rode-os até passarem.",
                    criterios_aceite=["testes passam"], depende_de=[2]),
        TarefaPlano(titulo="Documentar", tipo="docs", descricao="Escreva o README.md com instalação e uso.",
                    criterios_aceite=["README.md existe"], depende_de=[2]),
    ])


class ExecutorProjeto:
    def __init__(self, serv, eventos: Optional[Callable[[str, str], None]] = None, confirmar=None):
        self.serv = serv
        self.cfg = serv.cfg
        self.store = ProjetoStore(self.cfg)
        self._eventos_ext = eventos or serv.eventos
        self.confirmar = confirmar if confirmar is not None else serv.confirmar
        self._con = sqlite3.connect(str(self.cfg.db_checkpoints), check_same_thread=False)
        from langgraph.checkpoint.sqlite import SqliteSaver

        self.checkpointer = SqliteSaver(self._con)
        self.grafo = self._construir()
        self.info: Optional[InfoProjeto] = None
        self.ctx = None

    # ------------------------------------------------------------ util
    def evento(self, tipo: str, msg: str) -> None:
        self._eventos_ext(tipo, msg)
        if self.info and tipo in ("fase", "tarefa", "revisao", "comando", "aviso", "erro"):
            self.store.diario(self.info, f"[{tipo}] {msg}")

    def _contexto(self, info: InfoProjeto):
        if self.ctx is None or str(self.ctx.workspace) != str(Path(info.pasta).resolve()):
            self.ctx = self.serv.contexto(Path(info.pasta), escopos=["global", f"projeto:{info.id}"],
                                          escopo_gravacao=f"projeto:{info.id}", eventos=self.evento,
                                          confirmar=self.confirmar)
        return self.ctx

    def _fase(self, fase: str) -> None:
        self.info.fase = fase
        self.info.status = "em_andamento"
        self.store.salvar_info(self.info)
        self.evento("fase", fase)

    def _arquivos(self, limite: int = 60) -> str:
        raiz = Path(self.info.pasta)
        itens = []
        for p in sorted(raiz.rglob("*")):
            rel = p.relative_to(raiz)
            if any(x.startswith(".") or x in ("__pycache__", "node_modules", ".venv") for x in rel.parts) or p.is_dir():
                continue
            itens.append(str(rel).replace("\\", "/"))
            if len(itens) >= limite:
                break
        return "\n".join(itens) or "(vazia)"

    # ------------------------------------------------------------ nós
    def no_pesquisar(self, estado: EstadoProjeto) -> dict:
        self._fase("pesquisa")
        if not self.cfg.projetos.pesquisar_antes_de_planejar:
            return {"pesquisa": "", "fase": "pesquisa"}
        ctx = self._contexto(self.info)
        usar_bib = self.serv.indice.status()["trechos"] > 0
        try:
            r = pesquisar(ctx, estado["objetivo"], usar_biblioteca=usar_bib, usar_web=True)
            md = relatorio_markdown(estado["objetivo"], r)
            (Path(self.info.pasta) / "PESQUISA.md").write_text(md, encoding="utf-8")
            self.evento("aviso" if r.avisos else "status", f"Pesquisa inicial com {len(r.fontes)} fonte(s)."
                        + ("".join(f" Aviso: {a}" for a in r.avisos)))
            resumo = r.resposta[:2500]
        except AgenteErro as e:
            if "conectar" in str(e).lower() or "demorou" in str(e).lower():
                raise
            self.evento("aviso", f"Pesquisa inicial falhou, sigo sem ela: {e}")
            resumo = ""
        return {"pesquisa": resumo, "fase": "pesquisa"}

    def no_planejar(self, estado: EstadoProjeto) -> dict:
        self._fase("planejamento")
        ctx = self._contexto(self.info)
        lembr = self.serv.memoria.recordar(estado["objetivo"], ctx.escopos_memoria)
        partes = [f"OBJETIVO: {estado['objetivo']}"]
        if estado.get("pesquisa"):
            partes.append(f"PESQUISA PRÉVIA (resumo, com fontes em PESQUISA.md):\n{estado['pesquisa'][:2500]}")
        if lembr:
            partes.append("LEMBRANÇAS RELEVANTES:\n" + "\n".join(f"- {x.texto}" for x in lembr))
        partes.append(f"ARQUIVOS JÁ EXISTENTES NA PASTA DO PROJETO:\n{self._arquivos()}")
        sistema = PROMPT_PLANEJADOR.replace("{max_tarefas}", str(self.cfg.projetos.max_tarefas))
        try:
            plano = self.serv.llm.chat_json([{"role": "system", "content": sistema},
                                             {"role": "user", "content": "\n\n".join(partes)}], Plano, max_tokens=3000)
        except SaidaInvalida as e:
            self.evento("aviso", f"Planejador falhou ({e}); usando plano padrão.")
            plano = plano_padrao(estado["objetivo"])
        tarefas = []
        for i, t in enumerate(plano.tarefas[: self.cfg.projetos.max_tarefas], start=1):
            tarefas.append({"id": i, "titulo": t.titulo.strip()[:120], "descricao": t.descricao.strip(), "tipo": t.tipo,
                            "criterios": t.criterios_aceite[:6], "depende_de": [d for d in t.depende_de if 0 < d < i],
                            "status": "pendente", "tentativas": 0, "resultado": "", "feedback": "", "arquivos": []})
        self.store.salvar_tarefas(self.info, tarefas, plano.resumo)
        self.evento("fase", f"Plano com {len(tarefas)} tarefa(s): " + "; ".join(t["titulo"] for t in tarefas))
        return {"tarefas": tarefas, "resumo_plano": plano.resumo, "atual": None, "fase": "planejamento"}

    def _proxima(self, tarefas: List[dict]) -> Optional[int]:
        feitas = {t["id"] for t in tarefas if t["status"] in ("concluida", "com_ressalvas", "falhou")}
        for i, t in enumerate(tarefas):
            if t["status"] in ("pendente", "em_andamento") and all(d in feitas for d in t.get("depende_de", [])):
                return i
        for i, t in enumerate(tarefas):  # dependências circulares/erradas: segue na ordem
            if t["status"] in ("pendente", "em_andamento"):
                return i
        return None

    def no_executar(self, estado: EstadoProjeto) -> dict:
        tarefas = [dict(t) for t in estado["tarefas"]]
        i = self._proxima(tarefas)
        if i is None:
            return {"atual": None}
        t = tarefas[i]
        t["status"] = "em_andamento"
        self.store.salvar_tarefas(self.info, tarefas, estado.get("resumo_plano", ""))
        self._fase(f"tarefa {t['id']}/{len(tarefas)}")
        self.evento("tarefa", f"Iniciando tarefa {t['id']}: {t['titulo']} (tentativa {t['tentativas'] + 1})")
        ctx = self._contexto(self.info)
        ctx.arquivos_alterados = set()
        ctx.comandos_executados = []
        papel = PAPEL_POR_TIPO.get(t["tipo"], "desenvolvedor")
        plano_txt = "\n".join(f"{x['id']}. [{x['status']}] {x['titulo']}" + (f" — resultado: {x['resultado'][:200]}" if x["resultado"] else "")
                              for x in tarefas)
        lembr = self.serv.memoria.recordar(f"{t['titulo']} {t['descricao']}", ctx.escopos_memoria, k=4)
        partes = [f"OBJETIVO DO PROJETO: {estado['objetivo']}",
                  f"PLANO:\n{plano_txt}",
                  f"SUA TAREFA AGORA (nº {t['id']}, tipo {t['tipo']}): {t['titulo']}\n{t['descricao']}",
                  "CRITÉRIOS DE ACEITE:\n" + ("\n".join(f"- {c}" for c in t["criterios"]) or "- tarefa cumprida"),
                  f"ARQUIVOS NA PASTA DO PROJETO:\n{self._arquivos()}"]
        if estado.get("pesquisa") and t["tipo"] in ("pesquisa", "docs", "codigo"):
            partes.append(f"RESUMO DA PESQUISA INICIAL (detalhes em PESQUISA.md):\n{estado['pesquisa'][:1200]}")
        if lembr:
            partes.append("LEMBRANÇAS:\n" + "\n".join(f"- {x.texto}" for x in lembr))
        if t.get("feedback"):
            partes.append(f"A REVISÃO ANTERIOR REPROVOU ESTA TAREFA. Corrija:\n{t['feedback']}")
        ag = AgenteReact(self.serv.llm, self.serv.registro, ctx, PAPEIS[papel], grupos=GRUPOS_POR_PAPEL[papel],
                         max_passos=self.cfg.projetos.max_passos_por_tarefa)
        res = ag.executar("\n\n".join(partes))
        t["resultado"] = res.resposta[:3000]
        t["arquivos"] = sorted(set(t.get("arquivos", [])) | ctx.arquivos_alterados)
        self.evento("tarefa", f"Tarefa {t['id']} executada em {len(res.passos)} passo(s); arquivos: "
                              f"{', '.join(sorted(ctx.arquivos_alterados)) or 'nenhum'}")
        ultimo = {"indice": i, "concluido": res.concluido, "motivo": res.motivo_parada,
                  "comandos": [{"comando": c["comando"], "codigo_saida": c["codigo_saida"], "saida": c["saida"][-1500:]}
                               for c in ctx.comandos_executados[-4:]],
                  "arquivos_alterados": sorted(ctx.arquivos_alterados)}
        self.store.salvar_tarefas(self.info, tarefas, estado.get("resumo_plano", ""))
        return {"tarefas": tarefas, "atual": i, "ultimo_resultado": ultimo, "fase": "execucao"}

    def _verificacoes(self, t: dict) -> tuple:
        """Checagens objetivas: sintaxe dos .py alterados e pytest (se houver testes). -> (ok, evidências)"""
        raiz = Path(self.info.pasta)
        (raiz / ".agente" / "tmp").mkdir(parents=True, exist_ok=True)
        evid, ok = [], True
        for rel in t.get("arquivos", []):
            p = raiz / rel
            if p.suffix == ".py" and p.exists():
                try:
                    py_compile.compile(str(p), doraise=True, cfile=str(raiz / ".agente" / "tmp" / "_chk.pyc"))
                except py_compile.PyCompileError as e:
                    ok = False
                    evid.append(f"ERRO DE SINTAXE em {rel}: {str(e)[-400:]}")
        tem_testes = any(raiz.glob("test_*.py")) or any(raiz.glob("tests/test_*.py")) or any(raiz.glob("tests/**/test_*.py"))
        if t["tipo"] in ("codigo", "teste") and tem_testes:
            try:
                r = rodar(self._contexto(self.info), "python -m pytest -q -x --no-header -p no:cacheprovider",
                          timeout=self.cfg.seguranca.timeout_comando)
                passou = r["codigo_saida"] == 0
                linhas = [x for x in r["saida"].strip().splitlines() if x.strip()]
                final = linhas[-1].strip(" =") if linhas else ""
                evid.append(f"pytest {'PASSOU' if passou else 'FALHOU'} (código {r['codigo_saida']}; {final[:120]}):\n"
                            f"{r['saida'][-1500:]}")
                if not passou:
                    ok = False
            except PermissaoNegada as e:
                evid.append(f"Não rodei os testes: {e}")
        for crit in t.get("criterios", []):
            for nome in _arquivos_citados(crit):
                if not (raiz / nome).exists():
                    ok = False
                    evid.append(f"Critério '{crit}': o arquivo {nome} não existe.")
        return ok, evid

    def no_revisar(self, estado: EstadoProjeto) -> dict:
        tarefas = [dict(x) for x in estado["tarefas"]]
        i = estado["atual"]
        t = tarefas[i]
        ult = estado.get("ultimo_resultado", {})
        ok_det, evid = self._verificacoes(t)
        if (t["tipo"] in ("codigo", "teste", "docs") and not ult.get("arquivos_alterados")
                and not ult.get("comandos") and not t.get("arquivos")):
            ok_det = False
            evid.append("ERRO: a tarefa não criou/alterou nenhum arquivo nem rodou comandos (nada foi feito).")
        if evid:
            self.evento("revisao", f"Verificações da tarefa {t['id']}: " + " | ".join(e.splitlines()[0][:200] for e in evid))
        if ult.get("motivo"):
            evid.append(f"O executor parou antes de concluir ({ult['motivo']}).")
        for c in ult.get("comandos", []):
            evid.append(f"$ {c['comando']} -> código {c['codigo_saida']}\n{c['saida'][-600:]}")
        aprovado = ok_det and ult.get("concluido", True)
        problemas = [] if aprovado else [e for e in evid if "ERRO" in e or "FALHOU" in e or "não existe" in e or "parou" in e]
        sugestoes = ""
        if aprovado:
            conteudo = []
            for rel in t.get("arquivos", [])[:5]:
                p = Path(self.info.pasta) / rel
                if p.is_file():
                    conteudo.append(f"--- {rel} ---\n{p.read_text(encoding='utf-8', errors='replace')[:1500]}")
            msg = (f"TAREFA: {t['titulo']} ({t['tipo']})\n{t['descricao']}\n\nCRITÉRIOS:\n" +
                   "\n".join(f"- {c}" for c in t["criterios"]) +
                   f"\n\nRESPOSTA DO EXECUTOR:\n{t['resultado'][:1500]}\n\nARQUIVOS ALTERADOS: {', '.join(t['arquivos']) or 'nenhum'}\n" +
                   ("\n".join(conteudo)) + "\n\nEVIDÊNCIAS:\n" + ("\n".join(evid) or "(nenhuma)"))
            try:
                rev = self.serv.llm.chat_json([{"role": "system", "content": PROMPT_REVISOR},
                                               {"role": "user", "content": msg}], Revisao, max_tokens=800)
                aprovado, problemas, sugestoes = rev.aprovado, rev.problemas, rev.sugestoes
            except SaidaInvalida as e:
                self.evento("aviso", f"Revisor não respondeu em JSON ({e}); aprovando com base nas verificações.")
        t["tentativas"] = t.get("tentativas", 0) + 1
        if aprovado:
            t["status"] = "concluida"
            t["feedback"] = ""
            self.evento("revisao", f"Tarefa {t['id']} APROVADA.")
        else:
            fb = "; ".join(problemas)[:1500] + (f" Sugestões: {sugestoes}" if sugestoes else "")
            t["feedback"] = fb or "A revisão reprovou sem detalhes."
            if t["tentativas"] > self.cfg.projetos.max_tentativas_revisao:
                t["status"] = "com_ressalvas" if ok_det else "falhou"
                self.evento("revisao", f"Tarefa {t['id']} encerrada como '{t['status']}' após {t['tentativas']} tentativa(s): {fb[:300]}")
            else:
                t["status"] = "pendente"
                self.evento("revisao", f"Tarefa {t['id']} REPROVADA (tentativa {t['tentativas']}): {fb[:300]}")
        self.store.salvar_tarefas(self.info, tarefas, estado.get("resumo_plano", ""))
        return {"tarefas": tarefas, "atual": None, "fase": "revisao"}

    def no_finalizar(self, estado: EstadoProjeto) -> dict:
        self._fase("finalizacao")
        tarefas = estado.get("tarefas", [])
        linhas = "\n".join(f"- {t['id']}. {t['titulo']} [{t['status']}] — {t['resultado'][:300]}" for t in tarefas)
        info_txt = f"OBJETIVO: {estado['objetivo']}\n\nTAREFAS:\n{linhas}\n\nARQUIVOS:\n{self._arquivos(100)}"
        try:
            rel = self.serv.llm.chat([{"role": "system", "content": PROMPT_RELATORIO},
                                      {"role": "user", "content": info_txt}], max_tokens=1500)
        except AgenteErro as e:
            if "conectar" in str(e).lower():
                raise
            rel = f"# Relatório\n\n{info_txt}"
        cont = {s: sum(1 for t in tarefas if t["status"] == s) for s in ("concluida", "com_ressalvas", "falhou")}
        cab = (f"# Relatório final — {self.info.nome}\n\n*Gerado em {time.strftime('%Y-%m-%d %H:%M')}. "
               f"Tarefas: {cont['concluida']} concluída(s), {cont['com_ressalvas']} com ressalvas, {cont['falhou']} com falha.*\n\n")
        (Path(self.info.pasta) / "RELATORIO.md").write_text(cab + rel, encoding="utf-8")
        if self.cfg.memoria.extrair_automaticamente:
            self.serv.memoria.extrair(self.serv.llm, f"Projeto: {estado['objetivo']}\n{linhas}\n\n{rel[:2000]}",
                                      f"projeto:{self.info.id}", origem=f"projeto:{self.info.id}")
        self.serv.memoria.lembrar(f"Projeto '{self.info.nome}' ({self.info.id}) concluído: {estado['objetivo'][:200]}",
                                  "fato", "global", origem=f"projeto:{self.info.id}")
        self.info.status = "concluido" if cont["falhou"] == 0 else "concluido_com_falhas"
        self.info.fase = "fim"
        self.store.salvar_info(self.info)
        self.evento("fase", f"Projeto finalizado ({self.info.status}). Relatório: RELATORIO.md")
        return {"relatorio": rel, "fase": "fim"}

    # ------------------------------------------------------------ grafo
    def _construir(self):
        from langgraph.graph import END, START, StateGraph

        g = StateGraph(EstadoProjeto)
        g.add_node("pesquisar", self.no_pesquisar)
        g.add_node("planejar", self.no_planejar)
        g.add_node("executar", self.no_executar)
        g.add_node("revisar", self.no_revisar)
        g.add_node("finalizar", self.no_finalizar)
        g.add_edge(START, "pesquisar")
        g.add_edge("pesquisar", "planejar")
        g.add_edge("planejar", "executar")
        g.add_conditional_edges("executar", lambda s: "revisar" if s.get("atual") is not None else "finalizar",
                                {"revisar": "revisar", "finalizar": "finalizar"})
        g.add_edge("revisar", "executar")
        g.add_edge("finalizar", END)
        return g.compile(checkpointer=self.checkpointer)

    def _config(self, pid: str) -> dict:
        n = self.cfg.projetos.max_tarefas * 2 * (self.cfg.projetos.max_tentativas_revisao + 2) + 20
        return {"configurable": {"thread_id": pid}, "recursion_limit": n}

    def _rodar(self, entrada, pid: str) -> dict:
        try:
            self.grafo.invoke(entrada, self._config(pid))
        except KeyboardInterrupt:
            self.info.status = "interrompido"
            self.info.erro = "interrompido pelo usuário (Ctrl+C)"
            self.store.salvar_info(self.info)
            self.evento("erro", "Interrompido pelo usuário. Retome com: nlr projeto retomar " + self.info.id)
            raise
        except Exception as e:  # noqa: BLE001
            self.info.status = "interrompido"
            self.info.erro = str(e)[:500]
            self.store.salvar_info(self.info)
            self.evento("erro", f"Projeto interrompido: {e}\nRetome com: nlr projeto retomar {self.info.id}")
            raise
        return {}

    def novo(self, objetivo: str, nome: Optional[str] = None) -> InfoProjeto:
        self.info = self.store.criar(objetivo, nome)
        self.info.thread = self.info.id
        self.store.salvar_info(self.info)
        self._rodar({"projeto_id": self.info.id, "objetivo": objetivo, "tarefas": [], "atual": None}, self.info.id)
        return self.store.carregar(self.info.id)

    def retomar(self, pid: str) -> InfoProjeto:
        self.info = self.store.carregar(pid)
        pid = self.info.thread or self.info.id
        if self.info.status.startswith("concluido"):
            self.evento("aviso", "Este projeto já foi concluído. Use 'nlr projeto continuar' para pedir mais trabalho.")
            return self.info
        snap = self.grafo.get_state(self._config(pid))
        self.info.erro = ""
        self.store.diario(self.info, "Retomando o projeto.")
        if snap and snap.values:
            self.evento("fase", f"Retomando do checkpoint (próximo passo: {', '.join(snap.next) or 'fim'}).")
            self._rodar(None, pid)
        else:
            # sem checkpoint (ex.: checkpoints.db apagado): reconstrói a partir de .agente/tarefas.json
            resumo, tarefas = self.store.carregar_tarefas(self.info)
            if not tarefas:
                self.evento("fase", "Sem checkpoint nem plano salvo: recomeçando do início.")
                self._rodar({"projeto_id": self.info.id, "objetivo": self.info.objetivo, "tarefas": [], "atual": None}, pid)
            else:
                for t in tarefas:
                    if t["status"] == "em_andamento":
                        t["status"] = "pendente"
                self.evento("fase", "Checkpoint não encontrado: reconstruindo o estado a partir de tarefas.json.")
                self.grafo.update_state(self._config(pid), {"projeto_id": self.info.id, "objetivo": self.info.objetivo,
                                                            "tarefas": tarefas, "resumo_plano": resumo, "atual": None,
                                                            "pesquisa": ""}, as_node="planejar")
                self._rodar(None, pid)
        return self.store.carregar(self.info.id)

    def continuar(self, pid: str, pedido: str) -> InfoProjeto:
        """Acrescenta trabalho a um projeto (novo ciclo de planejamento sobre a mesma pasta)."""
        self.info = self.store.carregar(pid)
        objetivo = f"{self.info.objetivo}\n\nNOVO PEDIDO (o projeto já existe; aproveite os arquivos atuais): {pedido}"
        self.info.objetivo = objetivo
        self.info.status = "em_andamento"
        self.store.salvar_info(self.info)
        thread = f"{self.info.id}::{int(time.time())}"
        self.info.thread = thread
        self.store.salvar_info(self.info)
        self.store.diario(self.info, f"Novo pedido: {pedido}")
        self._rodar({"projeto_id": self.info.id, "objetivo": objetivo, "tarefas": [], "atual": None, "pesquisa": ""},
                    thread)
        return self.store.carregar(self.info.id)

    def estado(self, pid: str) -> dict:
        try:
            info = self.store.carregar(pid)
            pid = info.thread or info.id
        except AgenteErro:
            pass
        snap = self.grafo.get_state(self._config(pid))
        return dict(snap.values) if snap and snap.values else {}

    def fechar(self) -> None:
        try:
            self._con.close()
        except Exception:  # noqa: BLE001
            pass


def _arquivos_citados(criterio: str) -> List[str]:
    """Extrai nomes de arquivo explícitos de critérios como 'arquivo X.py existe'."""
    import re

    if "exist" not in criterio.lower():
        return []
    return [m for m in re.findall(r"[\w./-]+\.(?:py|md|txt|json|toml|yaml|yml|csv|html|js|ts|cfg|ini)\b", criterio)
            if not m.startswith(("http", "/")) and ".." not in m]
