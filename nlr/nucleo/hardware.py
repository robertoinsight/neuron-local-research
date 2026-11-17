"""Detecta RAM, GPU e VRAM sem dependências extras (Windows, Linux e macOS)."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class Hardware:
    sistema: str
    ram_gb: float
    cpus: int
    gpu: str = ""
    vram_gb: float = 0.0

    def dict(self) -> dict:
        return asdict(self)

    def max_parametros_b(self) -> float:
        """Tamanho aproximado de modelo (bilhões de parâmetros, Q4_K_M ~0,6 GB/B) que cabe com folga."""
        if self.vram_gb >= 4:
            # GPU + parte na RAM (offload) ainda é usável; consideramos VRAM + 1/4 da RAM livre
            util = self.vram_gb * 0.9 + max(0.0, self.ram_gb - 8) * 0.25
        else:
            util = max(0.0, self.ram_gb - 4) * 0.5  # só CPU: lento, mas funciona
        return round(max(0.5, util / 0.6), 1)


def _ram_gb() -> float:
    try:
        if os.name == "nt":
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEM()
            m.dwLength = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
            return m.ullTotalPhys / 1024 ** 3
        if os.path.exists("/proc/meminfo"):
            for linha in open("/proc/meminfo", encoding="utf-8"):
                if linha.startswith("MemTotal:"):
                    return int(linha.split()[1]) / 1024 ** 2
        if platform.system() == "Darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=5)) / 1024 ** 3
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def _gpu() -> tuple:
    smi = shutil.which("nvidia-smi")
    if not smi and os.name == "nt":
        c = r"C:\Windows\System32\nvidia-smi.exe"
        smi = c if os.path.exists(c) else None
    if smi:
        try:
            out = subprocess.check_output([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                          timeout=8, text=True)
            nome, mem = out.strip().splitlines()[0].rsplit(",", 1)
            return nome.strip(), float(mem) / 1024
        except Exception:  # noqa: BLE001
            pass
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "Apple Silicon (memória unificada)", _ram_gb() * 0.7
    return "", 0.0


_CACHE: dict = {}


def detectar(forcar: bool = False) -> Hardware:
    if "hw" in _CACHE and not forcar:
        return _CACHE["hw"]
    gpu, vram = _gpu()
    hw = Hardware(sistema=f"{platform.system()} {platform.release()}", ram_gb=round(_ram_gb(), 1),
                  cpus=os.cpu_count() or 1, gpu=gpu, vram_gb=round(vram, 1))
    _CACHE["hw"] = hw
    return hw


def resumo(hw: Optional[Hardware] = None) -> str:
    from ..i18n import t

    hw = hw or detectar()
    return t("hw.resumo", ram=hw.ram_gb, gpu=hw.gpu or t("hw.sem_gpu"), vram=hw.vram_gb, cpus=hw.cpus)
