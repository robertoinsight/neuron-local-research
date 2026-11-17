"""Plugin de exemplo: copie este arquivo para criar suas próprias ferramentas.

Todo arquivo .py desta pasta é carregado automaticamente (config: plugins.pastas).
"""
from datetime import datetime

from pydantic import BaseModel, Field

from nlr.ferramentas.registro import ferramenta


class ArgsVazio(BaseModel):
    pass


@ferramenta("data_hora", "Informa a data e a hora atuais do computador.", permissao="leitura",
            grupos={"util", "pesquisa", "codigo"})
def data_hora(ctx, args: ArgsVazio) -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


class ArgsContar(BaseModel):
    texto: str = Field(description="texto a analisar")


@ferramenta("contar_palavras", "Conta palavras e caracteres de um texto.", permissao="leitura", grupos={"util"})
def contar_palavras(ctx, args: ArgsContar) -> str:
    return f"{len(args.texto.split())} palavra(s), {len(args.texto)} caractere(s)"
