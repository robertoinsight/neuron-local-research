"""Exceções com mensagens em português, prontas para mostrar ao usuário."""


class AgenteErro(Exception):
    """Erro genérico do agente (mensagem já amigável)."""


class BackendIndisponivel(AgenteErro):
    """O servidor de modelos (Ollama, LM Studio, llama.cpp...) não respondeu."""


class SaidaInvalida(AgenteErro):
    """O modelo não devolveu uma resposta no formato esperado, mesmo após novas tentativas."""


class PermissaoNegada(AgenteErro):
    """A política de segurança bloqueou a ação."""
