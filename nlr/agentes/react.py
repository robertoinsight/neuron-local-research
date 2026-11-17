"""Laço de agente com ferramentas (pensar -> agir -> observar), robusto para modelos pequenos.

Dois modos (modelo.modo_ferramentas):
  * json   — o modelo devolve {"pensamento", "ferramenta", "argumentos"} validado por JSON Schema (padrão;
             benchmarks de 2026 mostram que o modo emulado é tão bom ou melhor que o nativo em modelos de 4-9B);
  * nativo — usa o parâmetro `tools` da API OpenAI (tool calling nativo do servidor).
Proteções: limite de passos, detecção de ações repetidas, orçamento de contexto com resumo automático.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..erros import AgenteErro, SaidaInvalida
from ..ferramentas.registro import Registro
from ..llm.texto import estimar_tokens
from ..i18n import instrucao_idioma, t
from ..nucleo import roteador_ferramentas
from ..nucleo.guarda import GuardaLoop
from ..prompts import PROMPT_RESUMIR, REGRAS_REACT

log = logging.getLogger(__name__)


class Acao(BaseModel):
    pensamento: str = Field("", description="raciocínio curto sobre o próximo passo")
    ferramenta: str = Field(description="nome da ferramenta a usar, ou 'finalizar'")
    argumentos: Dict[str, Any] = Field(default_factory=dict, description="argumentos da ferramenta")


@dataclass
class Passo:
    n: int
    pensamento: str
    ferramenta: str
    argumentos: dict
    observacao: str


@dataclass
class ResultadoReact:
    resposta: str
    passos: List[Passo] = field(default_factory=list)
    concluido: bool = True
    motivo_parada: str = ""


def _obs_curta(texto: str, limite: int) -> str:
    return texto if len(texto) <= limite else texto[: limite // 2] + "\n[...]\n" + texto[-limite // 2:]


_PLACEHOLDERS = ("resultado final para o usuário", "final result for the user", "...", "resposta", "",
                 "criei notas.md com 3 tópicos")


def _eh_placeholder(texto: str) -> bool:
    import difflib

    x = texto.strip().strip(".").lower()
    return x in _PLACEHOLDERS or any(difflib.SequenceMatcher(None, x, p).ratio() > 0.8 for p in _PLACEHOLDERS if p)


class AgenteReact:
    def __init__(self, llm, registro: Registro, ctx, papel_prompt: str, grupos: Optional[List[str]] = None,
                 max_passos: Optional[int] = None, rotear: bool = True):
        self.llm = llm
        self.ctx = ctx
        self.todas = registro.listar(grupos) if grupos else registro.listar()
        self.ferramentas = list(self.todas)
        self.registro = Registro()
        for f in self.todas:
            self.registro.registrar(f)
        self.papel_prompt = papel_prompt
        self.perfil = getattr(llm, "perfil", None)
        self._max_passos_pedido = max_passos
        self.max_passos = max_passos or (self.perfil.max_passos if self.perfil else 10)
        self.rotear = rotear
        self.cfg = ctx.cfg
        self.modo = self.cfg.modelo.modo_ferramentas
        self.guarda = GuardaLoop()

    def _selecionar(self, tarefa: str) -> None:
        """Roteador: só as ferramentas relevantes (modelos pequenos erram menos com menos opções)."""
        if self.rotear and self.perfil:
            self.ferramentas = roteador_ferramentas.selecionar(self.todas, tarefa, self.perfil.max_ferramentas)
            if len(self.ferramentas) < len(self.todas):
                self.ctx.evento("status", f"Ferramentas: {', '.join(f.nome for f in self.ferramentas)}")

    def _executar_ferramenta(self, nome: str, args: dict) -> str:
        f = self.registro.obter(nome)
        if f is None:
            import difflib

            perto = difflib.get_close_matches(nome, [x.nome for x in self.todas], n=2, cutoff=0.85)
            if len(perto) == 1:  # erro de digitação claro (ex.: leer_arquivo): corrige sozinho e avisa o modelo
                obs = self._executar_ferramenta(perto[0], args)
                return f"(nome corrigido: '{nome}' -> '{perto[0]}')\n{obs}"

            nomes = [x.nome for x in self.ferramentas]
            msg = t("ferr.inexistente", nome=nome, lista=", ".join(nomes))
            sug = difflib.get_close_matches(nome, [x.nome for x in self.todas], n=1, cutoff=0.6)
            return msg + (t("ferr.parecida", sugestao=sug[0]) if sug else "")
        if f not in self.ferramentas:  # o modelo pediu uma ferramenta fora da seleção: libera (expansão)
            self.ferramentas.append(f)
        return self.registro.executar(nome, args, self.ctx)

    # ------------------------------------------------------------ prompt
    def _sistema(self) -> str:
        lista = "\n".join(f.assinatura() for f in self.ferramentas)
        lista += "\n- finalizar(resposta: string): encerra a tarefa com o resultado final."
        return f"{self.papel_prompt}\n\nFERRAMENTAS:\n{lista}{REGRAS_REACT}\n{instrucao_idioma()}"

    def _mensagens(self, tarefa: str, passos: List[Passo], resumo: str) -> List[dict]:
        msgs = [{"role": "system", "content": self._sistema()},
                {"role": "user", "content": tarefa}]
        if resumo:
            msgs.append({"role": "user", "content": f"RESUMO DO PROGRESSO ATÉ AQUI:\n{resumo}"})
        orc = int(self.cfg.modelo.contexto_tokens * (self.perfil.fracao_historico if self.perfil else 0.6))
        lim_rec = self.perfil.obs_recente if self.perfil else 6000
        lim_ant = self.perfil.obs_antiga if self.perfil else 600
        usados = sum(estimar_tokens(m["content"]) for m in msgs)
        blocos = []
        # passos mais recentes com observação completa; antigos encurtados
        for i, p in enumerate(passos):
            recente = i >= len(passos) - 2
            obs = _obs_curta(p.observacao, lim_rec if recente else lim_ant)
            acao = json.dumps({"pensamento": p.pensamento, "ferramenta": p.ferramenta, "argumentos": p.argumentos},
                              ensure_ascii=False)
            if not recente and len(acao) > 800:
                acao = json.dumps({"pensamento": p.pensamento[:200], "ferramenta": p.ferramenta,
                                   "argumentos": "(omitidos)"}, ensure_ascii=False)
            blocos.append([{"role": "assistant", "content": acao},
                           {"role": "user", "content": f"OBSERVAÇÃO (passo {p.n}):\n{obs}"}])
        total = usados + sum(estimar_tokens(m["content"]) for b in blocos for m in b)
        while total > orc and len(blocos) > 2:
            removido = blocos.pop(0)
            total -= sum(estimar_tokens(m["content"]) for m in removido)
        for b in blocos:
            msgs += b
        if passos:
            msgs.append({"role": "user", "content": t("react.passo", n=len(passos) + 1, max=self.max_passos)})
        return msgs

    def _resumir(self, passos: List[Passo], resumo_antigo: str) -> str:
        texto = resumo_antigo + "\n" + "\n".join(
            f"Passo {p.n}: {p.ferramenta}({json.dumps(p.argumentos, ensure_ascii=False)[:300]}) -> {p.observacao[:500]}"
            for p in passos)
        try:
            return self.llm.chat([{"role": "system", "content": PROMPT_RESUMIR}, {"role": "user", "content": texto}],
                                 max_tokens=500, temperatura=0.1)
        except AgenteErro:
            return texto[-3000:]

    # ------------------------------------------------------------ decisão
    def _decidir(self, msgs: List[dict]) -> Acao:
        if self.modo == "nativo":
            tools = [f.openai_tool() for f in self.ferramentas] + [{
                "type": "function", "function": {"name": "finalizar", "description": "Encerra com a resposta final.",
                                                 "parameters": {"type": "object", "properties": {
                                                     "resposta": {"type": "string"}}, "required": ["resposta"]}}}]
            r = self.llm.chat_ferramentas(msgs, tools)
            if r.chamadas:
                c = r.chamadas[0]
                return Acao(pensamento=r.texto[:300], ferramenta=c.nome, argumentos=c.argumentos)
            return Acao(pensamento="", ferramenta="finalizar", argumentos={"resposta": r.texto})
        return self.llm.chat_json(msgs, Acao, temperatura=0.1)

    # ------------------------------------------------------------ laço
    def executar(self, tarefa: str) -> ResultadoReact:
        passos: List[Passo] = []
        resumo = ""
        self.guarda = GuardaLoop()
        if hasattr(self.llm, "preparar"):
            try:  # resolve modelo/contexto/perfil ANTES de escolher as ferramentas
                self.llm.preparar()
                self.perfil = self.llm.perfil
                self.max_passos = self._max_passos_pedido or self.perfil.max_passos
            except AgenteErro:
                pass
        self._selecionar(tarefa)
        for n in range(1, self.max_passos + 1):
            msgs = self._mensagens(tarefa, passos, resumo)
            if sum(estimar_tokens(m["content"]) for m in msgs) > self.cfg.modelo.contexto_tokens * 0.75 and len(passos) > 3:
                resumo = self._resumir(passos[:-2], resumo)
                passos_antigos = passos[:-2]
                passos = passos[-2:]
                self.ctx.evento("status", t("react.resumi", n=len(passos_antigos)))
                msgs = self._mensagens(tarefa, passos, resumo)
            try:
                acao = self._decidir(msgs)
            except SaidaInvalida as e:
                log.warning("Ação inválida: %s", e)
                return ResultadoReact(resposta=t("react.nao_continuou", erro=e), passos=passos, concluido=False,
                                      motivo_parada="saida_invalida")
            self.ctx.evento("pensamento", acao.pensamento)
            if acao.ferramenta in ("finalizar", "final", "responder", "resposta_final"):
                resp = acao.argumentos.get("resposta") or acao.argumentos.get("texto") or acao.pensamento
                if not isinstance(resp, str):
                    resp = json.dumps(resp, ensure_ascii=False)
                if _eh_placeholder(resp) and not passos and not getattr(self, "_corrigiu_final", False):
                    self._corrigiu_final = True  # copiou o exemplo do prompt sem fazer nada: corrige uma vez
                    passos.append(Passo(n, acao.pensamento, "finalizar", acao.argumentos,
                                        "ERRO: você finalizou copiando o EXEMPLO, sem fazer a tarefa. Use as "
                                        "ferramentas para realizar a TAREFA e só depois finalize descrevendo o que fez."))
                    continue
                if _eh_placeholder(resp) and passos:  # modelos pequenos às vezes copiam o exemplo do prompt
                    resp = "\n".join(f"- {p.ferramenta}: {p.observacao[:300]}" for p in passos[-5:])
                return ResultadoReact(resposta=resp.strip(), passos=passos)
            v = self.guarda.antes(acao.ferramenta, acao.argumentos)
            if v.acao == "parar":
                return ResultadoReact(resposta=v.mensagem + "\n" + self._resumir(passos, resumo), passos=passos,
                                      concluido=False, motivo_parada="repeticao")
            if v.acao == "avisar":
                obs = v.mensagem
            else:
                obs = self._executar_ferramenta(acao.ferramenta, acao.argumentos)
                extra = self.guarda.depois(obs)
                if extra:
                    obs += "\n" + extra
            self.ctx.evento("observacao", obs[:500])
            passos.append(Passo(n, acao.pensamento, acao.ferramenta, acao.argumentos, obs))
        # acabou o limite: pede um fechamento
        resumo_final = self._resumir(passos, resumo)
        return ResultadoReact(resposta=t("react.limite", max=self.max_passos, resumo=resumo_final),
                              passos=passos, concluido=False, motivo_parada="limite_passos")
