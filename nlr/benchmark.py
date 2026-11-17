"""nlr benchmark: mede o modelo carregado NO SEU PC e recomenda perfil e contexto.

Tarefas padrão (iguais para todos, para comparar resultados entre máquinas):
  1. velocidade — gera ~200 tokens e mede tokens/s e tempo até a resposta;
  2. JSON — 5 schemas diferentes; mede acerto na 1ª tentativa e com correção;
  3. ferramentas — 3 tarefas curtas do agente (criar arquivo, ler e responder, editar) numa pasta temporária;
  4. inhearsay — resume uma conversa com uma ordem CONDICIONAL e mede se o resumo perde a condição.
Os resultados ficam em dados/benchmarks/*.json.
"""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, List, Literal, Optional

from pydantic import BaseModel

from .erros import AgenteErro


class _Pessoa(BaseModel):
    nome: str
    idade: int


class _Lista(BaseModel):
    itens: List[str]
    total: int


class _Classe(BaseModel):
    sentimento: Literal["positivo", "negativo", "neutro"]
    confianca: float


class _Evento(BaseModel):
    titulo: str
    data: str
    participantes: List[str]


class _Calc(BaseModel):
    expressao: str
    resultado: float


TAREFAS_JSON = [
    (_Pessoa, "Extraia: 'Ana tem 31 anos e mora em Recife.'", lambda r: r.nome.lower().startswith("ana") and r.idade == 31),
    (_Lista, "Liste 3 cores primárias e o total.", lambda r: len(r.itens) == 3 and r.total == 3),
    (_Classe, "Classifique: 'Adorei o jogo, muito divertido!'", lambda r: r.sentimento == "positivo"),
    (_Evento, "Extraia: 'Reunião de sprint em 2026-11-10 com Bia e Caio.'",
     lambda r: "2026-11-10" in r.data and len(r.participantes) == 2),
    (_Calc, "Calcule 17 * 3 e devolva a expressão e o resultado.", lambda r: abs(r.resultado - 51) < 0.01),
]

TAREFAS_FERR = [
    ("Crie o arquivo ola.txt com o texto: oi mundo", lambda p: (p / "ola.txt").exists() and
     "oi mundo" in (p / "ola.txt").read_text(encoding="utf-8").lower()),
    ("Leia o arquivo dados.txt e responda qual é o número secreto que está nele.", None),
    ("No arquivo config.ini, troque 'modo=lento' por 'modo=rapido'.",
     lambda p: "modo=rapido" in (p / "config.ini").read_text(encoding="utf-8")),
]

CONVERSA_INHEARSAY = [
    {"role": "user", "content": "Quero um script que organize meus sprites por pasta."},
    {"role": "assistant", "content": "Posso fazer. Proponho separar por personagem e por animação."},
    {"role": "user", "content": "Antes de implementar, me mostre o plano para eu aprovar. Só depois que eu aprovar você "
                                "pode apagar as pastas antigas."},
    {"role": "assistant", "content": "Entendido. Vou preparar o plano."},
]


@dataclass
class Resultado:
    modelo: str
    backend: str
    contexto: int
    perfil: str
    hardware: dict
    tokens_por_segundo: float = 0.0
    segundos_resposta: float = 0.0
    json_primeira: float = 0.0
    json_com_correcao: float = 0.0
    ferramentas: float = 0.0
    inhearsay: float = 0.0
    recomendacao: dict = field(default_factory=dict)
    detalhes: List[str] = field(default_factory=list)
    quando: str = ""


def _velocidade(llm) -> tuple:
    msgs = [{"role": "user", "content": "Escreva um parágrafo de cerca de 150 palavras sobre pixel art."}]
    antes = dict(llm.uso_tokens)
    t0 = time.time()
    txt = llm.chat(msgs, max_tokens=256, temperatura=0.7)
    dt = max(1e-3, time.time() - t0)
    saida = llm.uso_tokens["saida"] - antes["saida"] or max(1, len(txt) // 4)
    return round(saida / dt, 1), round(dt, 1)


def _json(llm) -> tuple:
    ok1 = ok2 = 0
    for modelo, pedido, checar in TAREFAS_JSON:
        for tent, conta in ((1, "1"), (3, "3")):
            try:
                r = llm.chat_json([{"role": "user", "content": pedido}], modelo, max_tokens=200, tentativas=tent)
                if checar(r):
                    if tent == 1:
                        ok1 += 1
                    ok2 += 1
                    break
            except AgenteErro:
                pass
            if tent == 3:
                break
    n = len(TAREFAS_JSON)
    return ok1 / n, ok2 / n


def _ferramentas(serv) -> float:
    from .agentes.react import AgenteReact
    from .prompts import PAPEIS

    ok = 0
    for tarefa, checar in TAREFAS_FERR:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "dados.txt").write_text("Anotações.\nO número secreto é 4721.\n", encoding="utf-8")
            (p / "config.ini").write_text("[geral]\nmodo=lento\n", encoding="utf-8")
            ctx = serv.contexto(p, confirmar=lambda a, b: False)
            ag = AgenteReact(serv.llm, serv.registro, ctx, PAPEIS["geral"], max_passos=5)
            try:
                res = ag.executar(tarefa)
                sucesso = checar(p) if checar else "4721" in res.resposta
            except AgenteErro:
                sucesso = False
            ok += int(bool(sucesso))
    return ok / len(TAREFAS_FERR)


def _inhearsay(serv) -> float:
    """1.0 = o resumo perdeu a condição (ruim); 0.0 = manteve. Usa o verificador sobre o resumo do próprio modelo."""
    from .nucleo import inhearsay
    from .nucleo.handoff import PROMPT_HANDOFF
    from .i18n import idioma_atual

    material = "\n".join(f"{m['role']}: {m['content']}" for m in CONVERSA_INHEARSAY)
    try:
        resumo = serv.llm.chat([{"role": "system", "content": PROMPT_HANDOFF[idioma_atual()]},
                                {"role": "user", "content": material}], max_tokens=400, temperatura=0.1)
    except AgenteErro:
        return 1.0
    v = inhearsay.verificar(resumo, [m["content"] for m in CONVERSA_INHEARSAY if m["role"] == "user"])
    perdeu = not inhearsay.CONDICAO.search(resumo)
    return round(max(v.taxa, 1.0 if perdeu else 0.0), 2)


def recomendar(r: Resultado, hw) -> dict:
    perfil = r.perfil
    if r.json_com_correcao < 0.6 or r.ferramentas < 0.34:
        perfil = "pequeno"
    elif r.json_primeira >= 0.8 and r.ferramentas >= 0.99 and r.perfil == "medio":
        perfil = "grande" if r.tokens_por_segundo >= 15 else "medio"
    if r.tokens_por_segundo < 5:
        ctx = 4096
    elif r.tokens_por_segundo < 15:
        ctx = 8192
    else:
        ctx = 16384 if (hw.vram_gb >= 8 or hw.ram_gb >= 32) else 8192
    uso = []
    if r.json_com_correcao >= 0.8 and r.ferramentas >= 0.66:
        uso.append("agente e projetos")
    if r.json_com_correcao >= 0.6:
        uso.append("pesquisa profunda")
    uso.append("conversa e perguntas à biblioteca")
    dica = ""
    if r.ferramentas < 0.5:
        dica = "Para projetos, use um modelo maior (7-9B) se o PC aguentar."
    if r.inhearsay >= 0.5:
        dica += " O resumo deste modelo perde condições: mantenha handoff.inhearsay: true."
    return {"perfil": perfil, "contexto_tokens": ctx, "bom_para": uso, "dica": dica.strip(),
            "max_parametros_b_neste_pc": hw.max_parametros_b()}


def executar(serv, progresso: Optional[Callable[[str], None]] = None, rapido: bool = False) -> Resultado:
    from .nucleo import hardware

    prog = progresso or (lambda s: None)
    llm = serv.llm
    info = llm.preparar()
    hw = hardware.detectar()
    r = Resultado(modelo=info["modelo_chat"], backend=info["backend"], contexto=info["contexto_tokens"],
                  perfil=(info["perfil"] or {}).get("nome", "medio"), hardware=hw.dict(),
                  quando=time.strftime("%Y-%m-%d %H:%M"))
    prog("1/4 velocidade")
    r.tokens_por_segundo, r.segundos_resposta = _velocidade(llm)
    prog("2/4 JSON")
    r.json_primeira, r.json_com_correcao = _json(llm)
    if not rapido:
        prog("3/4 ferramentas")
        r.ferramentas = _ferramentas(serv)
        prog("4/4 inhearsay")
        r.inhearsay = _inhearsay(serv)
    r.contexto = serv.cfg.modelo.contexto_tokens
    r.recomendacao = recomendar(r, hw)
    return r


def salvar(cfg, r: Resultado) -> Path:
    pasta = cfg.dir_dados / "benchmarks"
    pasta.mkdir(parents=True, exist_ok=True)
    nome = "".join(c if c.isalnum() else "-" for c in r.modelo)[:60]
    p = pasta / f"{time.strftime('%Y%m%d-%H%M%S')}-{nome}.json"
    p.write_text(json.dumps(asdict(r), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def historico(cfg) -> List[dict]:
    pasta = cfg.dir_dados / "benchmarks"
    if not pasta.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(pasta.glob("*.json"))]
