"""Ferramentas de arquivos. Escrita/remoção só dentro do workspace (garantido pela Politica)."""
from __future__ import annotations

import fnmatch
import shutil
from typing import Optional

from pydantic import BaseModel, Field

from ..biblioteca.carregadores import CARREGADORES, carregar_arquivo
from ..erros import AgenteErro
from .registro import ferramenta

MAX_LEITURA = 12000


class ArgsLer(BaseModel):
    caminho: str = Field(description="caminho do arquivo (relativo à pasta do projeto ou absoluto)")
    linha_inicial: int = Field(1, description="primeira linha a ler")
    linha_final: Optional[int] = Field(None, description="última linha (vazio = até o fim)")


@ferramenta("ler_arquivo", "Lê um arquivo de texto/código (ou extrai o texto de PDF/DOCX/XLSX) com números de linha.",
            permissao="leitura", grupos={"arquivos", "codigo", "pesquisa"})
def ler_arquivo(ctx, a: ArgsLer) -> str:
    p = ctx.politica.checar_leitura(a.caminho)
    if not p.exists():
        return f"ERRO: arquivo não encontrado: {a.caminho}"
    if p.is_dir():
        return f"ERRO: '{a.caminho}' é uma pasta. Use listar_arquivos."
    if p.suffix.lower() in (".pdf", ".docx", ".xlsx", ".xlsm") and p.suffix.lower() in CARREGADORES:
        segs = carregar_arquivo(p)
        texto = "\n\n".join((f"[{s.local}]\n" if s.local else "") + s.texto for s in segs)
        return texto[:MAX_LEITURA] + ("\n[... truncado]" if len(texto) > MAX_LEITURA else "")
    raw = p.read_bytes()
    if b"\x00" in raw[:4096]:
        return f"ERRO: '{a.caminho}' parece ser binário."
    linhas = raw.decode("utf-8", errors="replace").splitlines()
    ini = max(1, a.linha_inicial)
    fim = min(len(linhas), a.linha_final or len(linhas))
    saida = []
    total = 0
    for i in range(ini, fim + 1):
        ln = f"{i:>4}| {linhas[i - 1]}"
        total += len(ln) + 1
        if total > MAX_LEITURA:
            saida.append(f"[... truncado na linha {i}; leia com linha_inicial={i}]")
            break
        saida.append(ln)
    cab = f"{p.name} ({len(linhas)} linhas)"
    return cab + "\n" + "\n".join(saida) if saida else cab + " (vazio)"


class ArgsListar(BaseModel):
    pasta: str = Field(".", description="pasta a listar (padrão: a pasta do projeto)")
    padrao: str = Field("*", description="filtro, ex.: *.py")


@ferramenta("listar_arquivos", "Lista arquivos e pastas (recursivo, até 300 itens).",
            permissao="leitura", grupos={"arquivos", "codigo", "pesquisa"})
def listar_arquivos(ctx, a: ArgsListar) -> str:
    raiz = ctx.politica.checar_leitura(a.pasta)
    if not raiz.exists():
        return f"ERRO: pasta não encontrada: {a.pasta}"
    itens = []
    for p in sorted(raiz.rglob("*")):
        rel = p.relative_to(raiz)
        if any(part in (".git", "__pycache__", ".venv", "node_modules", ".agente", ".pytest_cache") for part in rel.parts):
            continue
        if p.is_file() and not fnmatch.fnmatch(p.name, a.padrao):
            continue
        itens.append(f"{rel}{'/' if p.is_dir() else ''}" + (f"  ({p.stat().st_size} bytes)" if p.is_file() else ""))
        if len(itens) >= 300:
            itens.append("[... mais itens omitidos]")
            break
    return "\n".join(itens) if itens else "(pasta vazia)"


class ArgsEscrever(BaseModel):
    caminho: str = Field(description="caminho do arquivo dentro da pasta do projeto")
    conteudo: str = Field(description="conteúdo COMPLETO do arquivo")


@ferramenta("escrever_arquivo", "Cria ou sobrescreve um arquivo (só dentro da pasta do projeto). Cria as pastas necessárias.",
            permissao="escrita", grupos={"arquivos", "codigo"})
def escrever_arquivo(ctx, a: ArgsEscrever) -> str:
    p = ctx.politica.checar_escrita(a.caminho)
    if p.exists() and p.is_dir():
        return f"ERRO: '{a.caminho}' é uma pasta."
    p.parent.mkdir(parents=True, exist_ok=True)
    existia = p.exists()
    p.write_text(a.conteudo, encoding="utf-8", newline="\n")
    rel = str(p.relative_to(ctx.workspace))
    ctx.arquivos_alterados.add(rel)
    n = a.conteudo.count("\n") + (1 if a.conteudo and not a.conteudo.endswith("\n") else 0)
    return f"OK: {'sobrescrevi' if existia else 'criei'} {rel} ({n} linhas)."


class ArgsEditar(BaseModel):
    caminho: str = Field(description="arquivo a editar")
    procurar: str = Field(description="trecho EXATO que existe hoje no arquivo")
    substituir: str = Field(description="texto novo que entra no lugar")


@ferramenta("editar_arquivo", "Substitui um trecho exato de um arquivo existente (edição pontual).",
            permissao="escrita", grupos={"arquivos", "codigo"})
def editar_arquivo(ctx, a: ArgsEditar) -> str:
    p = ctx.politica.checar_escrita(a.caminho)
    if not p.exists():
        return f"ERRO: arquivo não encontrado: {a.caminho}. Use escrever_arquivo para criar."
    txt = p.read_text(encoding="utf-8", errors="replace")
    n = txt.count(a.procurar)
    if n == 0:
        return "ERRO: o trecho em 'procurar' não foi encontrado. Leia o arquivo e copie o trecho exato."
    if n > 1:
        return f"ERRO: o trecho aparece {n} vezes; inclua mais linhas de contexto para ficar único."
    p.write_text(txt.replace(a.procurar, a.substituir, 1), encoding="utf-8", newline="\n")
    rel = str(p.relative_to(ctx.workspace))
    ctx.arquivos_alterados.add(rel)
    return f"OK: editei {rel}."


class ArgsApagar(BaseModel):
    caminho: str = Field(description="arquivo ou pasta (dentro do projeto) a apagar")


@ferramenta("apagar", "Apaga um arquivo ou pasta DENTRO da pasta do projeto.", permissao="escrita",
            grupos={"arquivos", "codigo"})
def apagar(ctx, a: ArgsApagar) -> str:
    p = ctx.politica.checar_remocao(a.caminho)
    if not p.exists():
        return f"Nada a apagar: {a.caminho} não existe."
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()
    rel = str(p.relative_to(ctx.workspace))
    ctx.arquivos_alterados.add(rel)
    return f"OK: apaguei {rel}."


class ArgsPasta(BaseModel):
    caminho: str = Field(description="pasta a criar dentro do projeto")


@ferramenta("criar_pasta", "Cria uma pasta (e as intermediárias) dentro do projeto.", permissao="escrita",
            grupos={"arquivos", "codigo"})
def criar_pasta(ctx, a: ArgsPasta) -> str:
    p = ctx.politica.checar_escrita(a.caminho)
    if p.exists() and not p.is_dir():
        raise AgenteErro(f"Já existe um arquivo com esse nome: {a.caminho}")
    p.mkdir(parents=True, exist_ok=True)
    return f"OK: pasta {p.relative_to(ctx.workspace)} pronta."
