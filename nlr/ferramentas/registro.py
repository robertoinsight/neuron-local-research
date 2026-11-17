"""Sistema de ferramentas extensível.

Para criar uma ferramenta nova, basta decorar uma função (em nlr/ferramentas/ ou num arquivo .py
da pasta plugins/):

    from pydantic import BaseModel, Field
    from nlr.ferramentas.registro import ferramenta

    class ArgsSomar(BaseModel):
        a: float = Field(description="primeiro número")
        b: float = Field(description="segundo número")

    @ferramenta("somar", "Soma dois números.", permissao="leitura", grupos={"util"})
    def somar(ctx, args: ArgsSomar) -> str:
        return str(args.a + args.b)

Permissões: leitura | escrita | execucao | rede | memoria | mcp. Grupos definem quais agentes enxergam a
ferramenta (pesquisa, arquivos, codigo, memoria, util, mcp).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Type

from pydantic import BaseModel, ValidationError

from ..erros import AgenteErro, PermissaoNegada
from ..i18n import t

log = logging.getLogger(__name__)


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    funcao: Callable[[Any, Any], str]
    modelo_args: Optional[Type[BaseModel]] = None
    schema: Optional[dict] = None  # usado quando não há modelo Pydantic (ex.: ferramentas MCP)
    permissao: str = "leitura"
    grupos: Set[str] = field(default_factory=set)
    origem: str = "interna"

    def schema_json(self) -> dict:
        if self.modelo_args is not None:
            s = self.modelo_args.model_json_schema()
        else:
            s = self.schema or {"type": "object", "properties": {}}
        return _limpar_schema(s)

    def assinatura(self) -> str:
        """Linha compacta para o prompt: nome(arg: tipo, ...) - descrição."""
        s = self.schema_json()
        req = set(s.get("required", []))
        partes = []
        for nome, p in (s.get("properties") or {}).items():
            tipo = p.get("type") or ("|".join(x.get("type", "?") for x in p.get("anyOf", [])) or "valor")
            desc = p.get("description", "")
            opc = "" if nome in req else "?"
            partes.append(f"{nome}{opc}: {tipo}" + (f" ({desc})" if desc else ""))
        return f"- {self.nome}({'; '.join(partes)}): {self.descricao}"

    def openai_tool(self) -> dict:
        return {"type": "function", "function": {"name": self.nome, "description": self.descricao,
                                                 "parameters": self.schema_json()}}


def _limpar_schema(s):
    if isinstance(s, dict):
        return {k: _limpar_schema(v) for k, v in s.items() if k != "title"}
    if isinstance(s, list):
        return [_limpar_schema(v) for v in s]
    return s


class Registro:
    def __init__(self):
        self._ferramentas: Dict[str, Ferramenta] = {}

    def registrar(self, f: Ferramenta, substituir: bool = True) -> None:
        if f.nome in self._ferramentas and not substituir:
            raise AgenteErro(f"Ferramenta duplicada: {f.nome}")
        self._ferramentas[f.nome] = f

    def remover(self, nome: str) -> None:
        self._ferramentas.pop(nome, None)

    def obter(self, nome: str) -> Optional[Ferramenta]:
        return self._ferramentas.get(nome)

    def nomes(self) -> List[str]:
        return sorted(self._ferramentas)

    def listar(self, grupos: Optional[Iterable[str]] = None) -> List[Ferramenta]:
        fs = sorted(self._ferramentas.values(), key=lambda f: f.nome)
        if grupos is None:
            return fs
        g = set(grupos)
        return [f for f in fs if f.grupos & g]

    def copia(self) -> "Registro":
        r = Registro()
        r._ferramentas = dict(self._ferramentas)
        return r

    def executar(self, nome: str, argumentos: Optional[dict], ctx) -> str:
        """Executa a ferramenta e SEMPRE devolve texto (erros viram mensagens para o modelo corrigir)."""
        f = self.obter(nome)
        if f is None:
            return t("ferr.inexistente", nome=nome, lista=", ".join(self.nomes()))
        argumentos = argumentos or {}
        if not isinstance(argumentos, dict):
            return t("ferr.args_nao_objeto")
        try:
            if f.modelo_args is not None:
                args = f.modelo_args.model_validate(argumentos)
            else:
                args = argumentos
        except ValidationError as e:
            erros = "; ".join(f"{'.'.join(str(x) for x in er['loc'])}: {er['msg']}" for er in e.errors()[:5])
            return t("ferr.args_invalidos", nome=nome, erros=erros, formato=_exemplo(f))
        try:
            if ctx is not None and hasattr(ctx, "evento"):
                ctx.evento("ferramenta", f"{nome}({_resumo_args(argumentos)})")
            r = f.funcao(ctx, args)
            return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, default=str)
        except PermissaoNegada as e:
            return f"PERMISSÃO NEGADA: {e}"
        except AgenteErro as e:
            return f"ERRO: {e}"
        except Exception as e:  # noqa: BLE001
            log.exception("Falha na ferramenta %s", nome)
            return f"ERRO inesperado em {nome}: {type(e).__name__}: {e}"


def _exemplo(f: "Ferramenta") -> str:
    """Exemplo JSON concreto da chamada (modelos pequenos corrigem melhor vendo um exemplo do que um schema)."""
    s = f.schema_json()
    ex = {}
    for nome, p in (s.get("properties") or {}).items():
        if nome not in set(s.get("required", [])):
            continue
        tipo = p.get("type", "string")
        ex[nome] = {"integer": 1, "number": 1.0, "boolean": True, "array": [], "object": {}}.get(tipo, "...")
    return json.dumps({"ferramenta": f.nome, "argumentos": ex}, ensure_ascii=False) + f"  ({f.assinatura()[2:]})"


def _resumo_args(a: dict) -> str:
    s = json.dumps(a, ensure_ascii=False)
    return s if len(s) <= 120 else s[:117] + "..."


REGISTRO_PADRAO = Registro()


def ferramenta(nome: str, descricao: str, permissao: str = "leitura", grupos: Optional[Set[str]] = None,
               registro: Optional[Registro] = None):
    """Decorador que registra a função como ferramenta. O tipo do 2º parâmetro define os argumentos."""

    def deco(fn):
        import inspect
        import typing

        dicas = typing.get_type_hints(fn)
        params = list(inspect.signature(fn).parameters)
        modelo = dicas.get(params[1]) if len(params) > 1 else None
        if modelo is not None and not (isinstance(modelo, type) and issubclass(modelo, BaseModel)):
            modelo = None
        (registro or REGISTRO_PADRAO).registrar(Ferramenta(
            nome=nome, descricao=descricao, funcao=fn, modelo_args=modelo, permissao=permissao,
            grupos=set(grupos or {"util"}), origem=fn.__module__))
        return fn

    return deco


_EMBUTIDAS_CARREGADAS = False


def carregar_embutidas() -> None:
    global _EMBUTIDAS_CARREGADAS
    if _EMBUTIDAS_CARREGADAS:
        return
    for mod in ("arquivos", "comandos", "pesquisa", "memoria", "kits", "visao"):
        importlib.import_module(f"{__package__}.{mod}")
    _EMBUTIDAS_CARREGADAS = True


def carregar_plugins(pastas: List[Path]) -> List[str]:
    """Importa cada .py das pastas de plugins (que usam @ferramenta) e plugins instalados via entry points."""
    carregados = []
    for pasta in pastas:
        if not pasta.exists():
            continue
        for arq in sorted(pasta.glob("*.py")):
            if arq.name.startswith("_"):
                continue
            nome_mod = f"agente_plugin_{arq.stem}"
            if nome_mod in sys.modules:
                carregados.append(arq.name)
                continue
            try:
                spec = importlib.util.spec_from_file_location(nome_mod, arq)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[nome_mod] = mod
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                if hasattr(mod, "registrar"):
                    mod.registrar(REGISTRO_PADRAO)
                carregados.append(arq.name)
            except Exception as e:  # noqa: BLE001
                log.warning("Plugin %s não carregou: %s", arq.name, e)
    try:
        from importlib.metadata import entry_points

        for ep in entry_points(group="nlr.ferramentas"):
            try:
                obj = ep.load()
                if callable(obj):
                    obj(REGISTRO_PADRAO)
                carregados.append(f"entry-point:{ep.name}")
            except Exception as e:  # noqa: BLE001
                log.warning("Plugin %s não carregou: %s", ep.name, e)
    except Exception:  # noqa: BLE001
        pass
    return carregados
