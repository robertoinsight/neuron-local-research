"""Política de segurança: onde o agente pode ler/escrever e quais comandos pode executar.

Regras padrão (veja docs/SEGURANCA.md):
  * escrita, criação e remoção de arquivos SOMENTE dentro da pasta de trabalho (workspace) do projeto/conversa;
  * leitura: workspace + pastas da biblioteca + seguranca.pastas_extra_leitura;
  * comandos: SEMPRE pedem confirmação, a menos que seguranca.modo_autonomo esteja ligado E o comando
    esteja na lista seguranca.comandos_permitidos (sem encadeamentos como ; && | `);
  * comandos perigosos (formatar disco, apagar recursivo, desligar, alterar registro, baixar-e-executar...) são
    bloqueados SEMPRE, mesmo no modo autônomo;
  * todo comando roda com tempo limite, na pasta do workspace e sem variáveis de ambiente com segredos.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from ..config import Config
from ..erros import PermissaoNegada

PADROES_PERIGOSOS = [
    (r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rR]", "remoção recursiva (rm -r)"),
    (r"\brm\s+(-[a-zA-Z]+\s+)*(/|~|\*|\.\.)", "remoção fora da pasta de trabalho"),
    (r"\b(rd|rmdir)\s+/s\b", "remoção recursiva de pasta (rd /s)"),
    (r"\bdel\s+(/[a-zA-Z]\s+)*/[sSqQ]\b", "remoção em massa (del /s /q)"),
    (r"Remove-Item\b.*-Recurse", "remoção recursiva (Remove-Item -Recurse)"),
    (r"(^|[\s;&|])format(\.com)?\s+[a-zA-Z]:|\b(mkfs(\.\w+)?|diskpart|fdisk|parted)\b|Format-Volume|Clear-Disk",
     "formatação/particionamento de disco"),
    (r"\bdd\s+if=", "escrita direta em disco (dd)"),
    (r"\b(shutdown|reboot|halt|poweroff)\b|Stop-Computer|Restart-Computer", "desligar/reiniciar o computador"),
    (r"\breg(\.exe)?\s+(delete|add|import)\b|Remove-ItemProperty|Set-ItemProperty\s+.*HK", "alteração do registro do Windows"),
    (r"\b(bcdedit|vssadmin|wbadmin|cipher\s+/w|takeown|icacls|cacls|attrib\s+.*\+s)\b", "comando de sistema sensível"),
    (r"\b(sudo|su|runas|doas)\b", "elevação de privilégios"),
    (r"\b(curl|wget)\b[^|]*\|\s*(sh|bash|zsh|python|pwsh|powershell)", "baixar e executar script"),
    (r"(iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b.*\|\s*(iex|Invoke-Expression)", "baixar e executar script"),
    (r"\bInvoke-Expression\b|\biex\s*\(", "execução dinâmica (Invoke-Expression)"),
    (r"Set-ExecutionPolicy", "mudança de política de execução"),
    (r"\bchmod\s+(-R\s+)?[0-7]*7[0-7]*\s+/", "permissões no sistema"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "fork bomb"),
    (r"\bgit\s+push\b", "publicar código (git push)"),
    (r"\bgit\s+(reset\s+--hard|clean\s+-[a-zA-Z]*f)", "descartar alterações do git"),
    (r"\b(net\s+user|net\s+localgroup|useradd|userdel|passwd)\b", "gerenciamento de usuários"),
    (r"\b(schtasks|crontab|at\s+\d)\b|Register-ScheduledTask", "agendamento de tarefas no sistema"),
    (r"\b(ssh|scp|sftp|ftp|telnet|nc|ncat|netcat)\b", "conexão de rede remota"),
    (r"(^|[\s\"'])(/etc/|/usr/|/bin/|/boot/|C:\\Windows|%SystemRoot%|%WINDIR%)", "pasta do sistema"),
    (r">\s*/dev/sd|\\\\\.\\PhysicalDrive", "escrita direta em dispositivo"),
]
METACARACTERES_FORA_ASPAS = re.compile(r"[;&|<>]")
EXPANSOES = re.compile(r"`|\$\(|\n|%[A-Za-z_]+%")
_ASPAS = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'')


def encadeia(cmd: str) -> bool:
    """True se o comando encadeia/redireciona/expande (fora de aspas), ex.: a && b, a | b, a > f, $(x)."""
    return bool(EXPANSOES.search(cmd) or METACARACTERES_FORA_ASPAS.search(_ASPAS.sub("", cmd)))
SEGREDOS_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|SENHA|CREDENTIAL|AUTH)", re.IGNORECASE)


@dataclass
class Decisao:
    acao: str  # "permitir" | "confirmar" | "bloquear"
    motivo: str


class Politica:
    def __init__(self, cfg: Config, workspace: Path, leitura_extra: Optional[List[Path]] = None,
                 confirmar: Optional[Callable[[str, str], bool]] = None):
        self.cfg = cfg
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.leitura = [self.workspace] + [p.resolve() for p in (leitura_extra or [])]
        self.leitura += cfg.pastas_biblioteca() + [cfg.resolver(p) for p in cfg.seguranca.pastas_extra_leitura]
        self.confirmar = confirmar  # função(titulo, detalhe) -> bool; None = não interativo (nega)
        self.extra_bloqueios = [(p, "bloqueado pela configuração") for p in cfg.seguranca.comandos_bloqueados]

    # ------------------------------------------------------------ caminhos
    def resolver(self, caminho: str) -> Path:
        p = Path(os.path.expandvars(os.path.expanduser(str(caminho).strip().strip('"').strip("'"))))
        if not p.is_absolute():
            p = self.workspace / p
        return p.resolve()

    @staticmethod
    def _dentro(p: Path, raiz: Path) -> bool:
        try:
            p.relative_to(raiz)
            return True
        except ValueError:
            return False

    def checar_leitura(self, caminho: str) -> Path:
        p = self.resolver(caminho)
        if not any(self._dentro(p, r) for r in self.leitura):
            raise PermissaoNegada(
                f"Leitura negada: '{p}' está fora da pasta de trabalho e da biblioteca. "
                "Para liberar, adicione a pasta em seguranca.pastas_extra_leitura no config.yaml.")
        return p

    def checar_escrita(self, caminho: str) -> Path:
        p = self.resolver(caminho)
        if not self._dentro(p, self.workspace):
            raise PermissaoNegada(
                f"Escrita negada: '{p}' fica fora da pasta de trabalho ({self.workspace}). "
                "O agente só cria e altera arquivos dentro da pasta do projeto.")
        partes = p.relative_to(self.workspace).parts
        if partes and partes[0] == ".agente" and len(partes) > 1 and partes[1] != "tmp":
            raise PermissaoNegada("A pasta .agente guarda o estado interno do projeto e não pode ser alterada.")
        return p

    def checar_remocao(self, caminho: str) -> Path:
        p = self.checar_escrita(caminho)
        if p == self.workspace:
            raise PermissaoNegada("Não é permitido apagar a própria pasta de trabalho.")
        return p

    # ------------------------------------------------------------ comandos
    def avaliar_comando(self, comando: str) -> Decisao:
        cmd = comando.strip()
        if not cmd:
            return Decisao("bloquear", "comando vazio")
        for padrao, motivo in PADROES_PERIGOSOS + self.extra_bloqueios:
            if re.search(padrao, cmd, flags=re.IGNORECASE):
                return Decisao("bloquear", f"comando perigoso: {motivo}")
        seg = self.cfg.seguranca
        if seg.modo_autonomo and not encadeia(cmd) and self.na_lista(cmd):
            return Decisao("permitir", "modo autônomo + comando na lista de permitidos")
        if seg.modo_autonomo and encadeia(cmd):
            return Decisao("confirmar", "o comando encadeia/redireciona (; && | > `) e precisa de confirmação")
        return Decisao("confirmar", "comandos precisam de confirmação (modo autônomo desligado ou comando fora da lista)")

    def na_lista(self, cmd: str) -> bool:
        base = cmd.strip()
        for prefixo in self.cfg.seguranca.comandos_permitidos:
            pf = prefixo.strip()
            if base == pf or base.startswith(pf + " "):
                return True
        return False

    def autorizar_comando(self, comando: str) -> None:
        d = self.avaliar_comando(comando)
        if d.acao == "permitir":
            return
        if d.acao == "bloquear":
            raise PermissaoNegada(f"Bloqueado: {d.motivo}. Comando: {comando}")
        if self.confirmar is None:
            raise PermissaoNegada(
                f"O comando precisa de confirmação e não há ninguém para confirmar ({d.motivo}). "
                "Rode pela linha de comando (agente) para aprovar, ou ligue seguranca.modo_autonomo e inclua o "
                f"comando em seguranca.comandos_permitidos. Comando: {comando}")
        if not self.confirmar("Executar comando?", f"{comando}\n(pasta: {self.workspace})\nMotivo da pergunta: {d.motivo}"):
            raise PermissaoNegada(f"O usuário não autorizou o comando: {comando}")

    def ambiente_limpo(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not SEGREDOS_ENV.search(k)}
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env
