"""Gera ../neuron-local-research.zip sem venv, caches, dados, projetos, logs, segredos e modelos.

Uso: python scripts/empacotar.py [saida.zip]"""
import fnmatch
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTAS_FORA = {".venv", "venv", "__pycache__", ".pytest_cache", "dados", "projetos", ".git", ".agente"}
ARQ_FORA = ["*.pyc", "*.log", ".env", "config.yaml", "*.gguf", "*.safetensors", "*.bin", "*.db", "*.egg-info"]


def incluir(rel: Path) -> bool:
    if any(p in PASTAS_FORA or p.endswith(".egg-info") for p in rel.parts[:-1]):
        return False
    return not any(fnmatch.fnmatch(rel.name, a) for a in ARQ_FORA)


def main():
    saida = Path(sys.argv[1] if len(sys.argv) > 1 else RAIZ.parent / "neuron-local-research.zip").resolve()
    n = 0
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(RAIZ.rglob("*")):
            rel = p.relative_to(RAIZ)
            if p.is_file() and incluir(rel):
                z.write(p, Path("neuron-local-research") / rel)
                n += 1
    print(f"Gerado {saida} ({n} arquivos, {saida.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
