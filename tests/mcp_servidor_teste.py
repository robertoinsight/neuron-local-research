"""Servidor MCP mínimo (stdio) usado nos testes."""
from mcp.server.mcpserver import MCPServer

srv = MCPServer("teste")


@srv.tool()
def somar(a: int, b: int) -> str:
    """Soma dois números inteiros."""
    return str(a + b)


@srv.tool()
def ecoar(texto: str) -> str:
    """Devolve o texto recebido."""
    return f"eco: {texto}"


if __name__ == "__main__":
    srv.run("stdio")
