"""Execução de comandos e de código Python, sempre sob a Politica (confirmação, lista, bloqueios, tempo limite)."""
from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid

from pydantic import BaseModel, Field

from ..erros import AgenteErro
from .registro import ferramenta


def _matar_arvore(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _trocar_python(cmd: str) -> str:
    """'python ...' usa o mesmo Python do agente (evita cair no Python da Microsoft Store no Windows)."""
    for nome in ("python3 ", "python ", "py "):
        if cmd.startswith(nome):
            return f'"{sys.executable}" ' + cmd[len(nome):]
    if cmd.startswith("pytest"):
        return f'"{sys.executable}" -m ' + cmd
    return cmd


def rodar(ctx, comando: str, timeout: int = 0) -> dict:
    pol = ctx.politica
    pol.autorizar_comando(comando)
    seg = ctx.cfg.seguranca
    timeout = timeout or seg.timeout_comando
    if seg.execucao == "docker":
        if not shutil.which("docker"):
            raise AgenteErro("seguranca.execucao é 'docker', mas o Docker não foi encontrado no PATH.")
        exec_cmd = ["docker", "run", "--rm", "--network", "none", "-v", f"{pol.workspace}:/trabalho", "-w", "/trabalho",
                    seg.imagem_docker, "sh", "-c", comando]
        shell = False
    else:
        exec_cmd = _trocar_python(comando)
        shell = True
    ctx.evento("comando", comando)
    ini = time.time()
    kw = dict(cwd=str(pol.workspace), env=pol.ambiente_limpo(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
              stdin=subprocess.DEVNULL, shell=shell)
    if os.name != "nt":
        kw["start_new_session"] = True
    else:
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(exec_cmd, **kw)
    try:
        saida, _ = proc.communicate(timeout=timeout)
        expirou = False
    except subprocess.TimeoutExpired:
        _matar_arvore(proc)
        saida, _ = proc.communicate()
        expirou = True
    texto = (saida or b"").decode("utf-8", errors="replace")
    lim = seg.max_saida_comando
    if len(texto) > lim:
        texto = texto[: lim // 2] + f"\n[... {len(texto) - lim} caracteres omitidos ...]\n" + texto[-lim // 2:]
    r = {"comando": comando, "codigo_saida": None if expirou else proc.returncode, "expirou": expirou,
         "segundos": round(time.time() - ini, 1), "saida": texto}
    ctx.comandos_executados.append(r)
    return r


def formatar(r: dict) -> str:
    if r["expirou"]:
        cab = f"TEMPO ESGOTADO após {r['segundos']}s (processo encerrado)."
    else:
        cab = f"código de saída {r['codigo_saida']} ({r['segundos']}s)"
    return f"$ {r['comando']}\n{cab}\n{r['saida'] or '(sem saída)'}"


class ArgsComando(BaseModel):
    comando: str = Field(description="comando a executar na pasta do projeto, ex.: python -m pytest -q")
    timeout: int = Field(0, description="segundos (0 = padrão da configuração)")


@ferramenta("executar_comando", "Executa um comando de terminal na pasta do projeto (pode pedir confirmação).",
            permissao="execucao", grupos={"codigo"})
def executar_comando(ctx, a: ArgsComando) -> str:
    return formatar(rodar(ctx, a.comando, a.timeout))


class ArgsPython(BaseModel):
    codigo: str = Field(description="código Python a executar (use print para mostrar resultados)")


@ferramenta("executar_python", "Executa um trecho de código Python na pasta do projeto e devolve a saída.",
            permissao="execucao", grupos={"codigo"})
def executar_python(ctx, a: ArgsPython) -> str:
    tmp = ctx.workspace / ".agente" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    arq = tmp / f"trecho_{uuid.uuid4().hex[:8]}.py"
    arq.write_text(a.codigo, encoding="utf-8")
    rel = arq.relative_to(ctx.workspace).as_posix()
    try:
        return formatar(rodar(ctx, f"python {shlex.quote(rel) if os.name != 'nt' else rel}"))
    finally:
        try:
            arq.unlink()
        except OSError:
            pass
