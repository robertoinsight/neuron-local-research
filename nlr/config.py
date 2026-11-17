"""Configuração do agente (config.yaml) com valores padrão pensados para GPU de 8 GB.

Ordem de busca do arquivo:
  1. caminho passado com --config;
  2. variável de ambiente AGENTE_CONFIG;
  3. ./config.yaml na pasta atual;
  4. ~/.agente-local/config.yaml.
Pastas relativas (dados, projetos, plugins) são resolvidas a partir da pasta do config.yaml.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from .erros import AgenteErro

# URLs padrão de cada backend (todos falam o protocolo OpenAI em /v1)
BACKENDS_PADRAO = {
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "llamacpp": "http://localhost:8080/v1",
    "openai_compat": "https://api.openai.com/v1",
}


def _validar_backend(v: str) -> str:
    v = (v or "").strip().lower()
    if v not in BACKENDS_PADRAO:
        raise ValueError(f"backend '{v}' desconhecido; use um de: {', '.join(BACKENDS_PADRAO)}")
    return v


class ModeloCfg(BaseModel):
    backend: str = "ollama"

    _v_backend = field_validator("backend")(classmethod(lambda cls, v: _validar_backend(v)))
    base_url: str = ""
    modelo_chat: str = "qwen3.5:9b"
    modelo_rapido: str = ""  # opcional: modelo menor para tarefas simples (roteamento, resumos)
    modelo_embeddings: str = "qwen3-embedding:0.6b"
    # opcional: modelo com visão (ex.: qwen2.5-vl-7b, gemma-3-12b, llava). Vazio = usa o modelo_chat se ele
    # tiver visão; senão, um modelo de visão já carregado no servidor (o NLR avisa qual).
    modelo_visao: str = ""
    api_key_env: str = ""  # nome da variável de ambiente com a chave (só para APIs na nuvem)
    temperatura: float = 0.2
    max_tokens: int = 2048
    contexto_tokens: int = 8192
    # true = lê o contexto real do servidor (LM Studio/Ollama/llama.cpp) e ajusta contexto_tokens sozinho
    contexto_auto: bool = True
    # auto | pequeno | medio | grande — perfil de tamanho do modelo (ajusta ferramentas, passos e orçamento)
    perfil: str = "auto"
    timeout: float = 300.0
    saida_estruturada: str = "auto"  # auto | json_schema | json_object | texto
    modo_ferramentas: str = "json"  # json (mais robusto em modelos pequenos) | nativo
    tentativas_json: int = 3
    mostrar_raciocinio: bool = False
    # Modelos "pensantes" (Qwen3/3.5, Gemma 4...): false desliga o pensamento (bem mais rápido em 8 GB).
    pensar: bool = False
    parametros_extras: Dict[str, object] = Field(default_factory=dict)  # enviados como extra_body (ex.: {"think": false})

    def url(self) -> str:
        return (self.base_url or BACKENDS_PADRAO.get(self.backend, "")).rstrip("/")


class FallbackCfg(BaseModel):
    ativado: bool = False
    backend: str = "openai_compat"

    _v_backend = field_validator("backend")(classmethod(lambda cls, v: _validar_backend(v)))
    base_url: str = "https://openrouter.ai/api/v1"
    modelo_chat: str = ""
    api_key_env: str = "OPENROUTER_API_KEY"
    usar_para_embeddings: bool = False
    modelo_embeddings: str = ""


class BibliotecaCfg(BaseModel):
    pastas: List[str] = Field(default_factory=list)
    extensoes: List[str] = Field(default_factory=lambda: [
        ".pdf", ".docx", ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".xlsx", ".xlsm", ".json",
        ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".hpp", ".cs",
        ".go", ".rs", ".rb", ".php", ".lua", ".gd", ".sh", ".ps1", ".sql", ".yaml", ".yml", ".toml", ".ini",
    ])
    ignorar: List[str] = Field(default_factory=lambda: [
        ".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode", "dist", "build",
        ".agente", "*.min.js",
    ])
    tamanho_trecho: int = 1200
    sobreposicao: int = 200
    max_arquivo_mb: float = 50.0
    embeddings: str = "backend"  # backend | nenhum (só busca por palavras-chave, BM25)
    reranker: str = "leve"  # nenhum | leve (sem dependências) | fastembed (cross-encoder ONNX)
    ocr: str = "auto"  # auto | rapidocr | tesseract | nenhum  (páginas escaneadas de PDF)
    ocr_idiomas: str = "por+eng"  # só para tesseract
    tabelas_pdf: bool = True  # usa pdfplumber se instalado
    peso_vetor: float = 1.0  # peso dos embeddings na fusão híbrida (BM25 = 1.0)
    modelo_reranker: str = "jinaai/jina-reranker-v2-base-multilingual"
    k: int = 8
    lote_embeddings: int = 32


class WebCfg(BaseModel):
    motor: str = "ddgs"  # ddgs | searxng
    searxng_url: str = ""
    regiao: str = "br-pt"
    max_resultados: int = 6
    paginas_para_ler: int = 3
    timeout: float = 15.0
    max_caracteres_pagina: int = 20000
    tamanho_trecho: int = 900
    max_trechos: int = 8
    max_trechos_por_pagina: int = 3
    cache_horas: float = 24.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/141.0 Safari/537.36"
    )


class MemoriaCfg(BaseModel):
    extrair_automaticamente: bool = True
    max_lembrancas_no_contexto: int = 6
    max_mensagens_historico: int = 20
    dias_para_esquecer: float = 90  # fatos inferidos não usados há N dias são esquecidos (0 = nunca)
    max_por_escopo: int = 300  # teto por escopo (global / projeto:X); literais e fixados não contam p/ corte


class ProjetosCfg(BaseModel):
    pasta: str = "projetos"
    max_tarefas: int = 12
    max_passos_por_tarefa: int = 10
    max_tentativas_revisao: int = 2
    pesquisar_antes_de_planejar: bool = True


class SegurancaCfg(BaseModel):
    modo_autonomo: bool = False
    comandos_permitidos: List[str] = Field(default_factory=lambda: [
        "python", "python3", "py", "pytest", "python -m pytest", "pip list", "pip show", "node", "npm test",
        "npm run", "git status", "git diff", "git log", "git init", "git add", "git commit", "dir", "ls", "echo",
    ])
    comandos_bloqueados: List[str] = Field(default_factory=list)
    timeout_comando: int = 120
    max_saida_comando: int = 8000
    pastas_extra_leitura: List[str] = Field(default_factory=list)
    execucao: str = "local"  # local | docker
    imagem_docker: str = "python:3.12-slim"


class ServidorMCP(BaseModel):
    command: str
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None
    permissao: str = "confirmar"  # confirmar | livre (as ferramentas desse servidor rodam sem perguntar)


class McpCfg(BaseModel):
    servidores: Dict[str, ServidorMCP] = Field(default_factory=dict)
    timeout: float = 60.0


class PluginsCfg(BaseModel):
    pastas: List[str] = Field(default_factory=lambda: ["plugins"])


class UiCfg(BaseModel):
    host: str = "127.0.0.1"
    porta: int = 7860


class KitPixelCfg(BaseModel):
    ativo: bool = False  # liga as ferramentas de pixel art para o agente e a aba na interface
    aseprite: str = ""  # caminho do Aseprite.exe (vazio = detectar: ASEPRITE, PATH, Program Files, Steam)
    pasta_saida: str = "pixel"  # onde salvar o que a interface/agente gera
    paleta_padrao: str = "db32"


class KitAbntCfg(BaseModel):
    ativo: bool = False
    norma_citacao: str = "2023"  # 2023 (Silva, 2020) | 2002 (SILVA, 2020)
    fonte: str = "Times New Roman"  # ou Arial
    autor: str = ""
    instituicao: str = ""
    curso: str = ""
    local: str = ""
    pasta_saida: str = "abnt"
    buscar_online: bool = True  # Crossref/OpenLibrary/Google Books e metatags das páginas


class KitsCfg(BaseModel):
    pixel: KitPixelCfg = Field(default_factory=KitPixelCfg)
    abnt: KitAbntCfg = Field(default_factory=KitAbntCfg)


class ProfundaCfg(BaseModel):
    """Pesquisa profunda (nlr pesquisar --profunda). 0 = automático pelo perfil do modelo."""
    profundidade: int = 0  # rodadas de busca (1-5)
    largura: int = 0  # subperguntas por rodada (2-8)
    pausa_segundos: float = 1.0  # entre buscas (evita limite de requisições do buscador)
    pasta_relatorios: str = "relatorios"
    formatos: List[str] = Field(default_factory=lambda: ["md"])  # md | docx | pdf | abnt (docx NBR 14724)


class BuscaReversaCfg(BaseModel):
    """Busca reversa de verdade ("achar imagens parecidas", como o Google Lens). DESLIGADA por padrão.

    provedor:
      desligado -> nada sai do seu PC (só a pesquisa pela DESCRIÇÃO, feita pelo modelo local);
      serpapi   -> envia a imagem (reduzida, sem EXIF) à SerpApi (Google Lens oficial via API). Precisa de
                   consentimento_envio: true e da chave SERPAPI_API_KEY no arquivo .env.
    Imagens em que o modelo de visão vê pessoas em destaque NUNCA são enviadas (sem reconhecimento facial).
    """
    provedor: str = "desligado"  # desligado | serpapi
    consentimento_envio: bool = False
    api_key_env: str = "SERPAPI_API_KEY"
    max_resultados: int = 8
    paginas_para_ler: int = 3


class VisaoCfg(BaseModel):
    """Análise de imagens com modelo de visão (v0.7). O modelo fica em modelo.modelo_visao."""
    modo_padrao: str = "minucioso"  # minucioso | geral | texto | pixel
    lado_max: int = 1536  # lado máximo enviado ao modelo (menor = mais rápido e menos VRAM)
    recortes: bool = True  # modo minucioso: também envia os 4 quadrantes ampliados (imagens > 1024 px)
    max_imagens: int = 4  # imagens por mensagem no chat
    max_tokens: int = 2048
    links_manuais: bool = True  # interface: botões para VOCÊ abrir Google Lens/Bing/TinEye e colar a imagem
    busca_reversa: BuscaReversaCfg = Field(default_factory=BuscaReversaCfg)


class HandoffCfg(BaseModel):
    """Novo chat automático: quando a conversa chega perto do limite de contexto, o NLR resume o estado salvo
    e continua num chat novo, ligado ao anterior."""
    ativado: bool = True
    limite: float = 0.8  # fração do contexto que dispara o novo chat
    inhearsay: bool = True  # verificador de "boato herdado": confere o resumo contra as mensagens literais


class Config(BaseModel):
    idioma: str = "pt"  # pt (português do Brasil) | en (English)
    handoff: HandoffCfg = Field(default_factory=HandoffCfg)
    profunda: ProfundaCfg = Field(default_factory=ProfundaCfg)
    kits: KitsCfg = Field(default_factory=KitsCfg)
    visao: VisaoCfg = Field(default_factory=VisaoCfg)
    modelo: ModeloCfg = Field(default_factory=ModeloCfg)
    fallback: FallbackCfg = Field(default_factory=FallbackCfg)
    biblioteca: BibliotecaCfg = Field(default_factory=BibliotecaCfg)
    web: WebCfg = Field(default_factory=WebCfg)
    memoria: MemoriaCfg = Field(default_factory=MemoriaCfg)
    projetos: ProjetosCfg = Field(default_factory=ProjetosCfg)
    seguranca: SegurancaCfg = Field(default_factory=SegurancaCfg)
    mcp: McpCfg = Field(default_factory=McpCfg)
    plugins: PluginsCfg = Field(default_factory=PluginsCfg)
    ui: UiCfg = Field(default_factory=UiCfg)
    pasta_dados: str = "dados"

    # preenchido em tempo de execução
    caminho_arquivo: Optional[str] = Field(default=None, exclude=True)

    # ------------------------------------------------------------ caminhos
    @property
    def home(self) -> Path:
        if self.caminho_arquivo:
            return Path(self.caminho_arquivo).resolve().parent
        return Path.cwd()

    def resolver(self, p: str) -> Path:
        q = Path(os.path.expandvars(os.path.expanduser(p)))
        return (q if q.is_absolute() else self.home / q).resolve()

    @property
    def dir_dados(self) -> Path:
        d = self.resolver(self.pasta_dados)
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def dir_projetos(self) -> Path:
        d = self.resolver(self.projetos.pasta)
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def db_principal(self) -> Path:
        return self.dir_dados / "agente.db"

    @property
    def db_biblioteca(self) -> Path:
        return self.dir_dados / "biblioteca.db"

    @property
    def db_checkpoints(self) -> Path:
        return self.dir_dados / "checkpoints.db"

    def pastas_biblioteca(self) -> List[Path]:
        return [self.resolver(p) for p in self.biblioteca.pastas]

    # ------------------------------------------------------------ salvar
    def para_yaml(self) -> str:
        data = self.model_dump(exclude={"caminho_arquivo"})
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

    def salvar(self, caminho: Optional[Path] = None) -> Path:
        alvo = Path(caminho or self.caminho_arquivo or "config.yaml")
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(self.para_yaml(), encoding="utf-8")
        self.caminho_arquivo = str(alvo.resolve())
        return alvo


def _carregar_env(base: Path) -> None:
    """Carrega o arquivo .env (segredos como chaves de API), se existir."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    for p in (base / ".env", Path.cwd() / ".env"):
        if p.exists():
            load_dotenv(p, override=False)


def localizar_config(caminho: Optional[str] = None) -> Optional[Path]:
    candidatos = []
    if caminho:
        candidatos.append(Path(caminho))
    for var in ("NLR_CONFIG", "AGENTE_CONFIG"):
        if os.environ.get(var):
            candidatos.append(Path(os.environ[var]))
    candidatos += [Path.cwd() / "config.yaml", Path.home() / ".nlr" / "config.yaml",
                   Path.home() / ".agente-local" / "config.yaml"]
    for c in candidatos:
        if c.exists():
            return c.resolve()
    return Path(caminho).resolve() if caminho else None


def carregar(caminho: Optional[str] = None) -> Config:
    p = localizar_config(caminho)
    if p is None or not p.exists():
        cfg = Config()
        cfg.caminho_arquivo = str(p) if p else None
        _carregar_env(cfg.home)
        return cfg
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise AgenteErro(f"O arquivo {p} tem um erro de formatação YAML:\n{e}") from e
    try:
        cfg = Config.model_validate(data)
    except ValidationError as e:
        linhas = [f"  - {'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
        raise AgenteErro(f"Configuração inválida em {p}:\n" + "\n".join(linhas)) from e
    cfg.caminho_arquivo = str(p)
    _carregar_env(cfg.home)
    return cfg
