"""Gera o Guia-Agente-Local.pdf juntando README + docs (precisa de: pip install markdown, e Google Chrome/Chromium).

Uso: python scripts/gerar_pdf.py [saida.pdf]
"""
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

RAIZ = Path(__file__).resolve().parent.parent
ORDEM = ["README.md", "docs/INSTALACAO.md", "docs/BIBLIOTECA.md", "docs/USO.md", "docs/ARQUITETURA.md",
         "docs/SEGURANCA.md", "docs/ESTENDER.md", "docs/SOLUCAO-DE-PROBLEMAS.md", "docs/PESQUISA.md"]

CSS = """
@page { size: A4; margin: 16mm 14mm 18mm 14mm; }
body { font-family: 'DejaVu Sans', 'Segoe UI', Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1d2330; }
h1 { color: #0b5394; border-bottom: 2px solid #0b5394; padding-bottom: 4px; font-size: 19pt; margin-top: 0; }
h2 { color: #0b5394; font-size: 14pt; margin-top: 18px; } h3 { font-size: 11.5pt; }
code { font-family: 'DejaVu Sans Mono', Consolas, monospace; font-size: 8.6pt; background: #f1f3f7; padding: 1px 3px; border-radius: 3px; }
pre { background: #f6f8fb; border: 1px solid #dfe3ea; border-radius: 5px; padding: 8px 10px; white-space: pre-wrap; word-wrap: break-word; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 8.8pt; page-break-inside: auto; }
th, td { border: 1px solid #ccd3de; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: #e8eef7; } tr { page-break-inside: avoid; }
.secao { page-break-before: always; } .secao:first-of-type { page-break-before: avoid; }
.capa { height: 250mm; display: flex; flex-direction: column; justify-content: center; text-align: center; }
.capa h1 { border: none; font-size: 32pt; } .capa p { font-size: 13pt; color: #444; }
.mermaid { text-align: center; margin: 10px 0; }
blockquote { border-left: 4px solid #9fb7d9; margin: 8px 0; padding: 2px 10px; color: #333; background: #f7f9fc; }
a { color: #0b5394; text-decoration: none; }
"""


def converter(md_texto: str) -> str:
    blocos = []

    def guarda(m):
        blocos.append(m.group(1))
        return f"\n\nMERMAID{len(blocos) - 1}FIM\n\n"

    md_texto = re.sub(r"```mermaid\n(.*?)```", guarda, md_texto, flags=re.S)
    corpo = markdown.markdown(md_texto, extensions=["tables", "fenced_code", "sane_lists"])
    for i, b in enumerate(blocos):
        corpo = corpo.replace(f"<p>MERMAID{i}FIM</p>", f'<div class="mermaid">{html.escape(b)}</div>')
    # links entre documentos viram texto simples no PDF
    corpo = re.sub(r'<a href="(?!http)[^"]*">(.*?)</a>', r"\1", corpo)
    return corpo


def main():
    saida = Path(sys.argv[1] if len(sys.argv) > 1 else RAIZ.parent / "Guia-Agente-Local.pdf").resolve()
    partes = ['<div class="capa"><h1>Neuron Local Research</h1><p>Guia completo: instalação, biblioteca, uso, arquitetura, '
              'segurança e extensão</p><p>Versão 1.0.0 · outubro de 2026</p></div>']
    for nome in ORDEM:
        partes.append(f'<div class="secao">{converter((RAIZ / nome).read_text(encoding="utf-8"))}</div>')
    pagina = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Neuron Local Research — Guia</title>
<style>{CSS}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{startOnLoad: true, theme: 'neutral', flowchart: {{useMaxWidth: true}}}});</script>
</head><body>{''.join(partes)}</body></html>"""
    tmp = Path(tempfile.mkdtemp()) / "guia.html"
    tmp.write_text(pagina, encoding="utf-8")
    chrome = next((c for c in ("google-chrome", "chromium", "chromium-browser", "chrome") if shutil.which(c)), None)
    if not chrome:
        sys.exit(f"Chrome/Chromium não encontrado. O HTML ficou em {tmp}; abra e imprima em PDF.")
    subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=20000", f"--print-to-pdf={saida}", tmp.as_uri()],
                   check=True, capture_output=True, timeout=180)
    print(f"PDF gerado: {saida}")


if __name__ == "__main__":
    main()
