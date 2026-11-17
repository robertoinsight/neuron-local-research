"""Cliente único para qualquer servidor compatível com a API OpenAI.

Backends suportados (escolha em modelo.backend no config.yaml):
  ollama        -> http://localhost:11434/v1
  lmstudio      -> http://localhost:1234/v1
  llamacpp      -> http://localhost:8080/v1   (llama-server)
  openai_compat -> qualquer API na nuvem compatível (OpenAI, OpenRouter, Groq...), com chave no .env

Recursos pensados para modelos pequenos:
  * saída estruturada (JSON Schema) com validação Pydantic e novas tentativas com o erro explicado;
  * rebaixamento automático json_schema -> json_object -> texto quando o servidor não suporta;
  * fallback opcional para uma API na nuvem quando o servidor local está fora do ar.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Type, TypeVar

import time
import httpx
import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from ..config import BACKENDS_PADRAO, Config
from ..erros import AgenteErro, BackendIndisponivel, SaidaInvalida
from ..i18n import t
from ..nucleo import descoberta
from ..nucleo import perfil as perfil_mod
from .texto import extrair_json, remover_raciocinio

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

DICAS_BACKEND = {
    "ollama": (
        "  1. O Ollama está instalado e aberto? (no Windows, procure o ícone da lhama perto do relógio)\n"
        "  2. Teste no terminal: ollama list\n"
        "  3. O modelo foi baixado? ollama pull {modelo}"
    ),
    "lmstudio": (
        "  1. O LM Studio está aberto?\n"
        "  2. Na aba Developer, o servidor está com Status: Running? (ou rode: lms server start)\n"
        "  3. Há um modelo carregado? (ou rode: lms load <modelo>)"
    ),
    "llamacpp": (
        "  1. O llama-server está rodando? Ex.: llama-server -m modelo.gguf --port 8080 --jinja\n"
        "  2. A porta em modelo.base_url confere?"
    ),
    "openai_compat": (
        "  1. Você está conectado à internet?\n"
        "  2. A chave de API está no arquivo .env (variável indicada em api_key_env)?"
    ),
}


@dataclass
class Endpoint:
    nome: str
    backend: str
    base_url: str
    modelo_chat: str
    modelo_embeddings: str
    api_key: str
    timeout: float
    extras: Dict[str, object] = field(default_factory=dict)
    _cliente: Optional[OpenAI] = None

    @property
    def cliente(self) -> OpenAI:
        if self._cliente is None:
            self._cliente = OpenAI(base_url=self.base_url, api_key=self.api_key or "sem-chave",
                                   timeout=self.timeout, max_retries=1)
        return self._cliente


@dataclass
class ChamadaFerramenta:
    id: str
    nome: str
    argumentos: dict


@dataclass
class RespostaChat:
    texto: str
    chamadas: List[ChamadaFerramenta] = field(default_factory=list)


class ClienteLLM:
    def __init__(self, cfg: Config, eventos: Optional[Callable[[str], None]] = None):
        self.cfg = cfg
        m = cfg.modelo
        self.eventos = eventos or (lambda s: None)
        self.principal = Endpoint(
            nome="principal", backend=m.backend, base_url=m.url(), modelo_chat=m.modelo_chat,
            modelo_embeddings=m.modelo_embeddings,
            api_key=os.environ.get(m.api_key_env, "") if m.api_key_env else _chave_padrao(m.backend),
            timeout=m.timeout, extras=_extras_pensamento(m.backend, m.pensar, m.parametros_extras),
        )
        f = cfg.fallback
        self.reserva: Optional[Endpoint] = None
        if f.ativado:
            chave = os.environ.get(f.api_key_env, "") if f.api_key_env else ""
            if f.modelo_chat and chave:
                self.reserva = Endpoint(
                    nome="reserva (nuvem)", backend=f.backend,
                    base_url=(f.base_url or BACKENDS_PADRAO.get(f.backend, "")).rstrip("/"),
                    modelo_chat=f.modelo_chat, modelo_embeddings=f.modelo_embeddings, api_key=chave,
                    timeout=m.timeout,
                )
            else:
                log.warning("fallback.ativado=true, mas falta modelo_chat ou a chave %s no .env", f.api_key_env)
        self.modelos_servidor: list = []
        self.ultima_resposta: float = 0.0
        self.info_modelo = None
        self.contexto_fonte = "config"
        self._ctx_confirmado = False
        self.perfil = perfil_mod.obter(m.perfil, descoberta.parametros_do_nome(m.modelo_chat), m.contexto_tokens)
        self._modo_estruturado = m.saida_estruturada  # pode ser rebaixado em tempo de execução
        self.usando_reserva = False
        self.uso_tokens = {"entrada": 0, "saida": 0, "chamadas": 0}

    # ------------------------------------------------------------ erros
    def _erro_amigavel(self, exc: Exception, ep: Endpoint, oque: str = "chat") -> AgenteErro:
        modelo = ep.modelo_embeddings if oque == "embeddings" else ep.modelo_chat
        if isinstance(exc, openai.APITimeoutError):
            return BackendIndisponivel(
                f"O servidor de modelos ({ep.backend}) demorou demais (limite de {ep.timeout:.0f}s).\n"
                "Em GPU de 8 GB, use um modelo menor/mais quantizado, reduza modelo.contexto_tokens "
                "ou aumente modelo.timeout no config.yaml."
            )
        if isinstance(exc, openai.APIConnectionError):
            dica = DICAS_BACKEND.get(ep.backend, "").format(modelo=modelo)
            return BackendIndisponivel(
                f"Não consegui conectar ao servidor de modelos '{ep.backend}' em {ep.base_url}.\n"
                f"Verifique:\n{dica}\nDepois rode: nlr doctor"
            )
        if isinstance(exc, openai.AuthenticationError):
            return AgenteErro(f"O servidor recusou a chave de API ({ep.nome}). Confira o arquivo .env.")
        if isinstance(exc, openai.NotFoundError):
            dica = f"ollama pull {modelo}" if ep.backend == "ollama" else "carregue o modelo no servidor"
            return AgenteErro(
                f"O modelo '{modelo}' não foi encontrado em {ep.backend}. Solução: {dica}.\n"
                "Use `nlr doctor` para listar os modelos disponíveis."
            )
        if isinstance(exc, openai.APIStatusError):
            msg = getattr(exc, "message", str(exc))
            if "context" in msg.lower() or "too long" in msg.lower():
                return AgenteErro(
                    "A conversa ficou maior que o contexto do modelo. Aumente o contexto ao carregar o modelo "
                    "(LM Studio: Context Length; Ollama: OLLAMA_CONTEXT_LENGTH) ou reduza modelo.contexto_tokens.\n"
                    f"Detalhe: {msg[:300]}"
                )
            return AgenteErro(f"Erro do servidor de modelos (HTTP {exc.status_code}): {msg[:400]}")
        return AgenteErro(f"Erro inesperado ao falar com o servidor de modelos: {exc}")

    def _endpoints(self) -> List[Endpoint]:
        eps = [self.principal]
        if self.reserva:
            eps.append(self.reserva)
        return eps

    # ------------------------------------------------------------ chamada base
    def _resolver_modelos(self, ep: Endpoint) -> None:
        """Resolve "auto", lê o contexto real do servidor e escolhe o perfil (uma vez por endpoint)."""
        if getattr(ep, "_resolvido", False):
            return
        if ep is not self.principal:
            if ep.modelo_chat in ("", "auto") or ep.modelo_embeddings == "auto":
                ids = [m.id for m in ep.cliente.models.list().data]
                if ep.modelo_chat in ("", "auto"):
                    chat = [i for i in ids if not descoberta.eh_embedding(i)]
                    if not chat:
                        raise AgenteErro(t("modelo.sem_chat", backend=ep.backend))
                    ep.modelo_chat = chat[0]
                if ep.modelo_embeddings == "auto":
                    emb = [i for i in ids if descoberta.eh_embedding(i)]
                    ep.modelo_embeddings = emb[0] if emb else ""
            ep._resolvido = True  # type: ignore[attr-defined]
            return
        try:
            modelos = descoberta.listar(ep.backend, ep.base_url, ep.api_key)
        except Exception as e:  # noqa: BLE001
            raise self._erro_amigavel(openai.APIConnectionError(request=httpx.Request("GET", ep.base_url)), ep) if _eh_conexao(e) else \
                AgenteErro(f"{e}") from e
        self.modelos_servidor = modelos
        esc = descoberta.escolher(modelos, ep.modelo_chat, ep.modelo_embeddings, ep.backend)
        for a in esc.avisos:
            self.eventos(a)
        ep.modelo_chat, ep.modelo_embeddings = esc.chat, esc.embeddings
        self.info_modelo = esc.info_chat
        self._ajustar_contexto(ep, esc)
        ep._resolvido = True  # type: ignore[attr-defined]

    def _ajustar_contexto(self, ep: Endpoint, esc) -> None:
        m = self.cfg.modelo
        ctx, fonte = 0, ""
        info = esc.info_chat
        if info and info.contexto_carregado:
            ctx, fonte = info.contexto_carregado, "servidor (carregado)"
        elif ep.backend == "ollama":
            try:
                maximo, num_ctx = descoberta.contexto_ollama(descoberta._raiz(ep.base_url), ep.modelo_chat)
                alvo = num_ctx or int(os.environ.get("OLLAMA_CONTEXT_LENGTH") or 0) or m.contexto_tokens
                ctx, fonte = (min(alvo, maximo) if maximo else alvo), "ollama /api/show"
            except Exception:  # noqa: BLE001
                pass
        elif info and info.contexto_max:
            # não carregado ainda: o servidor carrega com o padrão dele; ficamos com o menor valor seguro
            ctx, fonte = min(info.contexto_max, m.contexto_tokens), "máximo do modelo x config"
        if m.contexto_auto and ctx >= 512:
            m.contexto_tokens = ctx
            self.contexto_fonte = fonte
            self.eventos(t("modelo.contexto", n=ctx, fonte=fonte))
        pb = info.parametros_b if info else descoberta.parametros_do_nome(ep.modelo_chat)
        self.perfil = perfil_mod.obter(m.perfil, pb, m.contexto_tokens)
        if m.contexto_auto:
            m.max_tokens = min(m.max_tokens, perfil_mod.max_tokens_para(self.perfil, m.contexto_tokens))
            m.tentativas_json = max(m.tentativas_json, self.perfil.tentativas_json)

    def _confirmar_contexto(self, ep: Endpoint) -> None:
        """Depois da 1ª resposta o modelo já está carregado: relê o contexto REAL (/api/ps, /api/v0) uma vez."""
        if ep is not self.principal or self._ctx_confirmado or not self.cfg.modelo.contexto_auto:
            return
        self._ctx_confirmado = True
        if self.contexto_fonte == "servidor (carregado)" or ep.backend not in ("ollama", "lmstudio"):
            return
        try:
            info = next((m for m in descoberta.listar(ep.backend, ep.base_url) if m.id == ep.modelo_chat), None)
        except Exception:  # noqa: BLE001
            return
        if info and info.contexto_carregado and info.contexto_carregado != self.cfg.modelo.contexto_tokens:
            self.cfg.modelo.contexto_tokens = info.contexto_carregado
            self.contexto_fonte = "servidor (carregado)"
            self.perfil = perfil_mod.obter(self.cfg.modelo.perfil, info.parametros_b, info.contexto_carregado)
            self.cfg.modelo.max_tokens = min(self.cfg.modelo.max_tokens,
                                             perfil_mod.max_tokens_para(self.perfil, info.contexto_carregado))
            self.eventos(t("modelo.contexto", n=info.contexto_carregado, fonte=self.contexto_fonte))

    def preparar(self) -> dict:
        """Conecta, resolve modelos e devolve um resumo (usado pelo doctor, CLI e API)."""
        self._resolver_modelos(self.principal)
        ep = self.principal
        # v0.5: relê o estado AGORA (antes ficava em cache desde a 1ª conexão -> "não carregado" eterno)
        try:
            self.modelos_servidor = descoberta.listar(ep.backend, ep.base_url, ep.api_key)
        except Exception:  # noqa: BLE001
            pass
        recente = bool(self.ultima_resposta) and (time.time() - self.ultima_resposta) < 300
        for m in self.modelos_servidor:
            if m.id == ep.modelo_chat and recente and not m.carregado and ep.backend not in ("ollama", "lmstudio"):
                m.carregado = True  # servidores sem /ps: respondeu há pouco => está carregado
        p = self.perfil
        return {"backend": self.principal.backend, "base_url": self.principal.base_url,
                "modelo_chat": self.principal.modelo_chat, "modelo_embeddings": self.principal.modelo_embeddings,
                "contexto_tokens": self.cfg.modelo.contexto_tokens, "contexto_fonte": self.contexto_fonte,
                "max_tokens": self.cfg.modelo.max_tokens, "perfil": p.dict() if p else None,
                "modelos": [m.dict() for m in self.modelos_servidor],
                "ultima_resposta": self.ultima_resposta}

    def _criar(self, ep: Endpoint, mensagens: List[dict], *, max_tokens: int, temperatura: float,
               modelo: Optional[str], response_format=None, tools=None, stream=False, extras: Optional[dict] = None):
        self._resolver_modelos(ep)
        kw = dict(model=modelo or ep.modelo_chat, messages=mensagens, max_tokens=max_tokens,
                  temperature=temperatura, stream=stream)
        if response_format is not None:
            kw["response_format"] = response_format
        if tools:
            kw["tools"] = tools
        if ep.extras or extras:
            kw["extra_body"] = {**(ep.extras or {}), **(extras or {})}
        try:
            r = ep.cliente.chat.completions.create(**kw)
            self.ultima_resposta = time.time()
            self._confirmar_contexto(ep)
            return r
        except openai.BadRequestError as e:
            # servidor que não aceita os parâmetros de pensamento: tira e tenta de novo uma vez
            chaves = {"reasoning_effort", "chat_template_kwargs", "think"}
            if ep.extras and chaves & set(ep.extras) and any(c in str(e).lower() for c in ("reason", "think", "template")):
                ep.extras = {k: v for k, v in ep.extras.items() if k not in chaves}
                kw.pop("extra_body", None)
                if ep.extras:
                    kw["extra_body"] = ep.extras
                return ep.cliente.chat.completions.create(**kw)
            raise

    def _com_fallback(self, fn, oque="chat"):
        ultimo: Optional[AgenteErro] = None
        for ep in self._endpoints():
            try:
                r = fn(ep)
                if ep is not self.principal and not self.usando_reserva:
                    self.usando_reserva = True
                    self.eventos("Servidor local indisponível: usando a API de reserva na nuvem.")
                return r
            except BackendIndisponivel as err:
                if ep is self.principal and self.reserva:
                    ultimo = err
                    continue
                raise
            except AgenteErro:
                raise
            except openai.BadRequestError:
                raise
            except Exception as e:  # noqa: BLE001
                err = self._erro_amigavel(e, ep, oque)
                if isinstance(err, BackendIndisponivel) and ep is self.principal and self.reserva:
                    ultimo = err
                    continue
                raise err from e
        raise ultimo or AgenteErro("Nenhum servidor de modelos disponível.")

    def _registrar_uso(self, r) -> None:
        self.uso_tokens["chamadas"] += 1
        u = getattr(r, "usage", None)
        if u:
            self.uso_tokens["entrada"] += getattr(u, "prompt_tokens", 0) or 0
            self.uso_tokens["saida"] += getattr(u, "completion_tokens", 0) or 0

    # ------------------------------------------------------------ texto
    def chat(self, mensagens: List[dict], *, max_tokens: Optional[int] = None, temperatura: Optional[float] = None,
             modelo: Optional[str] = None, ao_receber: Optional[Callable[[str], None]] = None,
             extras: Optional[dict] = None) -> str:
        """Resposta em texto (sem os blocos de raciocínio). Se ao_receber for dado, usa streaming.
        extras: parâmetros a mais no corpo da requisição (ex.: {"repeat_penalty": 1.1})."""
        mt = max_tokens or self.cfg.modelo.max_tokens
        temp = self.cfg.modelo.temperatura if temperatura is None else temperatura

        def fazer(ep: Endpoint):
            if ao_receber is None:
                r = self._criar(ep, mensagens, max_tokens=mt, temperatura=temp, modelo=modelo if ep is self.principal else None,
                                extras=extras if ep is self.principal else None)
                self._registrar_uso(r)
                return _texto_da_resposta(r, self.cfg.modelo.mostrar_raciocinio)
            partes = []
            filtro = FiltroRaciocinio(esconder=not self.cfg.modelo.mostrar_raciocinio)
            for ch in self._criar(ep, mensagens, max_tokens=mt, temperatura=temp,
                                  modelo=modelo if ep is self.principal else None, stream=True,
                                  extras=extras if ep is self.principal else None):
                if not ch.choices:
                    continue
                pedaco = getattr(ch.choices[0].delta, "content", None)
                if pedaco:
                    saida = filtro.feed(pedaco)
                    if saida:
                        partes.append(saida)
                        ao_receber(saida)
            resto = filtro.flush()
            if resto:
                partes.append(resto)
                ao_receber(resto)
            self.uso_tokens["chamadas"] += 1
            return "".join(partes).strip()

        try:
            return self._com_fallback(fazer)
        except openai.BadRequestError as e:
            raise self._erro_amigavel(e, self.principal) from e

    # ------------------------------------------------------------ JSON validado
    def _formato(self, modelo_pyd: Type[BaseModel]):
        modo = self._modo_estruturado
        if modo == "texto":
            return None
        if modo == "json_object":
            return {"type": "json_object"}
        schema = modelo_pyd.model_json_schema()
        return {"type": "json_schema", "json_schema": {"name": modelo_pyd.__name__, "schema": schema}}

    def chat_json(self, mensagens: List[dict], modelo_pyd: Type[T], *, max_tokens: Optional[int] = None,
                  temperatura: float = 0.1, modelo: Optional[str] = None, tentativas: Optional[int] = None) -> T:
        """Pede uma resposta JSON que obedeça ao schema do modelo Pydantic; valida e tenta de novo se errar."""
        schema_txt = json.dumps(_schema_compacto(modelo_pyd), ensure_ascii=False)
        msgs = list(mensagens)
        instr = f"\n\n{t('json.instrucao')}\n{schema_txt}"
        if msgs and msgs[0]["role"] == "system":
            msgs[0] = {"role": "system", "content": msgs[0]["content"] + instr}
        else:
            msgs.insert(0, {"role": "system", "content": instr.strip()})
        n = tentativas or self.cfg.modelo.tentativas_json
        mt = max_tokens or self.cfg.modelo.max_tokens
        ultimo_erro = ""
        bruto = ""
        cortada = {"sim": False}
        teto = max(mt, min(4 * mt, int(self.cfg.modelo.contexto_tokens * 0.6)))
        for tentativa in range(n):
            fmt = self._formato(modelo_pyd)

            def fazer(ep: Endpoint, fmt=fmt, mt=mt):
                r = self._criar(ep, msgs, max_tokens=mt, temperatura=temperatura,
                                modelo=modelo if ep is self.principal else None, response_format=fmt)
                self._registrar_uso(r)
                try:
                    cortada["sim"] = r.choices[0].finish_reason == "length"
                except (AttributeError, IndexError):
                    cortada["sim"] = False
                return _texto_da_resposta(r, False)

            try:
                bruto = self._com_fallback(fazer)
            except openai.BadRequestError as e:
                # servidor não aceita esse response_format: rebaixa e tenta de novo
                if self._modo_estruturado in ("auto", "json_schema"):
                    log.info("Servidor recusou json_schema; usando json_object. (%s)", e)
                    self._modo_estruturado = "json_object"
                    continue
                if self._modo_estruturado == "json_object":
                    self._modo_estruturado = "texto"
                    continue
                raise self._erro_amigavel(e, self.principal) from e
            dado = None if cortada["sim"] else extrair_json(bruto)
            if cortada["sim"]:
                ultimo_erro = (f"a resposta foi CORTADA por passar do limite de {mt} tokens. Seja bem mais curto: "
                               "conteúdo de arquivo com no máximo ~80 linhas por chamada (depois acrescente com "
                               "editar_arquivo), sem comentários longos")
                mt = min(teto, mt * 2)
            elif dado is None:
                ultimo_erro = t("json.sem_json")
            else:
                try:
                    return modelo_pyd.model_validate(dado)
                except ValidationError as e:
                    ultimo_erro = "; ".join(
                        f"{'.'.join(str(x) for x in er['loc']) or 'raiz'}: {er['msg']}" for er in e.errors()[:5]
                    )
            log.info("JSON inválido (tentativa %d/%d): %s", tentativa + 1, n, ultimo_erro)
            msgs = msgs + [
                {"role": "assistant", "content": bruto[:600] if cortada["sim"] else bruto[:2000]},
                {"role": "user", "content": t("json.recusado", erro=ultimo_erro)},
            ]
        raise SaidaInvalida(
            f"O modelo não devolveu um JSON válido após {n} tentativas ({ultimo_erro}).\n"
            "Modelos muito pequenos erram mais: tente um modelo maior (ex.: qwen3.5:9b ou gemma4:e4b) "
            f"ou aumente modelo.tentativas_json. Início da resposta: {bruto[:200]!r}"
        )

    # ------------------------------------------------------------ ferramentas nativas
    def chat_ferramentas(self, mensagens: List[dict], ferramentas: List[dict], *, max_tokens: Optional[int] = None,
                         temperatura: float = 0.1) -> RespostaChat:
        mt = max_tokens or self.cfg.modelo.max_tokens

        def fazer(ep: Endpoint):
            r = self._criar(ep, mensagens, max_tokens=mt, temperatura=temperatura, modelo=None, tools=ferramentas)
            self._registrar_uso(r)
            msg = r.choices[0].message
            chamadas = []
            for tc in getattr(msg, "tool_calls", None) or []:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = extrair_json(tc.function.arguments or "") or {}
                chamadas.append(ChamadaFerramenta(id=tc.id or tc.function.name, nome=tc.function.name, argumentos=args))
            return RespostaChat(texto=remover_raciocinio(msg.content or ""), chamadas=chamadas)

        try:
            return self._com_fallback(fazer)
        except openai.BadRequestError as e:
            raise self._erro_amigavel(e, self.principal) from e

    # ------------------------------------------------------------ embeddings
    def embeddings(self, textos: List[str]) -> List[List[float]]:
        def fazer(ep: Endpoint):
            self._resolver_modelos(ep)
            modelo = ep.modelo_embeddings
            if not modelo:
                raise AgenteErro("Nenhum modelo de embeddings configurado (modelo.modelo_embeddings).")
            r = ep.cliente.embeddings.create(model=modelo, input=textos)
            return [d.embedding for d in sorted(r.data, key=lambda d: d.index)]

        eps = [self.principal]
        if self.reserva and self.cfg.fallback.usar_para_embeddings and self.reserva.modelo_embeddings:
            eps.append(self.reserva)
        ultimo: Optional[Exception] = None
        for ep in eps:
            try:
                return fazer(ep)
            except AgenteErro:
                raise
            except Exception as e:  # noqa: BLE001
                ultimo = self._erro_amigavel(e, ep, "embeddings")
        raise ultimo  # type: ignore[misc]

    # ------------------------------------------------------------ diagnóstico
    def listar_modelos(self, ep: Optional[Endpoint] = None) -> List[str]:
        ep = ep or self.principal
        try:
            return [m.id for m in ep.cliente.models.list().data]
        except Exception as e:  # noqa: BLE001
            raise self._erro_amigavel(e, ep) from e


def _eh_conexao(e: Exception) -> bool:
    import requests

    return isinstance(e, (requests.ConnectionError, requests.Timeout, ConnectionError))


def _chave_padrao(backend: str) -> str:
    return {"ollama": "ollama", "lmstudio": "lm-studio", "llamacpp": "sem-chave"}.get(backend, "")


def _extras_pensamento(backend: str, pensar: bool, extras: Dict[str, object]) -> Dict[str, object]:
    """Parâmetros para ligar/desligar o "pensamento" de modelos como Qwen3.5 e Gemma 4."""
    ex = dict(extras or {})
    if pensar:
        return ex
    if backend == "ollama" and "think" not in ex:
        ex.setdefault("reasoning_effort", "none")
    elif backend == "llamacpp":
        ex.setdefault("chat_template_kwargs", {"enable_thinking": False})
    return ex


def _texto_da_resposta(r, mostrar_raciocinio: bool) -> str:
    if not r.choices:
        return ""
    msg = r.choices[0].message
    texto = msg.content or ""
    if mostrar_raciocinio:
        rac = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
        if rac:
            texto = f"<think>{rac}</think>\n{texto}"
        return texto.strip()
    return remover_raciocinio(texto)


def _schema_compacto(modelo_pyd: Type[BaseModel]) -> dict:
    """Schema simplificado (sem títulos) para caber melhor no contexto de modelos pequenos."""
    def limpar(x):
        if isinstance(x, dict):
            return {k: limpar(v) for k, v in x.items() if k not in ("title",)}
        if isinstance(x, list):
            return [limpar(v) for v in x]
        return x
    return limpar(modelo_pyd.model_json_schema())


class FiltroRaciocinio:
    """Filtro de streaming que esconde o que está entre <think> e </think>."""

    ABRE, FECHA = "<think>", "</think>"

    def __init__(self, esconder: bool = True):
        self.esconder = esconder
        self.dentro = False
        self.buf = ""

    @staticmethod
    def _sufixo_parcial(buf: str, tag: str) -> int:
        for k in range(min(len(tag) - 1, len(buf)), 0, -1):
            if tag.startswith(buf[-k:]):
                return k
        return 0

    def feed(self, texto: str) -> str:
        if not self.esconder:
            return texto
        self.buf += texto
        out = []
        while True:
            tag = self.FECHA if self.dentro else self.ABRE
            i = self.buf.find(tag)
            if i != -1:
                if not self.dentro:
                    out.append(self.buf[:i])
                self.buf = self.buf[i + len(tag):]
                self.dentro = not self.dentro
                continue
            manter = self._sufixo_parcial(self.buf, tag)
            ate = len(self.buf) - manter
            if not self.dentro:
                out.append(self.buf[:ate])
            self.buf = self.buf[ate:]
            break
        return "".join(out)

    def flush(self) -> str:
        resto = "" if (self.dentro or not self.esconder) else self.buf
        self.buf = ""
        return resto
