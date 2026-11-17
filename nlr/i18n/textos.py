"""Textos da interface (CLI, erros, avisos, prompts curtos). Chaves iguais nos dois idiomas."""

PT = {
    "app.nome": "Neuron Local Research",
    "app.descricao": "Neuron Local Research (NLR) — agente de pesquisa e projetos que roda no seu computador.",
    "prompt.idioma": "Responda sempre em português do Brasil, a menos que o usuário peça outro idioma.",
    # modelos / servidor
    "modelo.auto_escolhido": "Nenhum modelo de chat estava carregado; escolhi '{modelo}' entre os disponíveis. "
                             "O servidor vai carregá-lo agora (pode demorar). Para fixar, use modelo.modelo_chat no config.yaml.",
    "modelo.auto_carregado": "Usando o modelo carregado: {modelo}",
    "modelo.emb_escolhido": "Modelo de embeddings detectado: {modelo}",
    "modelo.sem_chat": "O servidor {backend} está no ar, mas não há nenhum modelo de chat disponível. "
                       "Baixe ou carregue um modelo (no LM Studio: aba Discover/My Models).",
    "modelo.nao_encontrado": "O modelo '{modelo}' não existe no servidor {backend}. Disponíveis: {lista}",
    "modelo.contexto": "Contexto real do modelo: {n} tokens (fonte: {fonte}).",
    "perfil.escolhido": "Perfil {perfil}: até {ferr} ferramentas por passo, {passos} passos, contexto {ctx} tokens.",
    "perfil.pequeno": "pequeno",
    "perfil.medio": "médio",
    "perfil.grande": "grande",
    # hardware
    "hw.resumo": "RAM {ram} GB | GPU: {gpu} | VRAM {vram} GB | CPUs {cpus}",
    "hw.sem_gpu": "não detectada",
    "hw.recomendacao": "Recomendado para este PC: modelos até ~{b}B parâmetros (quantização Q4_K_M).",
    # ferramentas / guarda
    "ferr.inexistente": "ERRO: a ferramenta '{nome}' não existe. Use exatamente um destes nomes: {lista}.",
    "ferr.parecida": " Você quis dizer '{sugestao}'?",
    "ferr.args_invalidos": "ERRO: argumentos inválidos para {nome}: {erros}. Corrija e envie de novo neste formato: {formato}",
    "ferr.args_nao_objeto": "ERRO: 'argumentos' precisa ser um objeto JSON, ex.: {{\"caminho\": \"a.txt\"}}.",
    "guarda.repeticao": "AVISO: você repetiu a mesma ação {n} vezes e o resultado não muda. Tente outra abordagem "
                        "ou use 'finalizar' explicando o que conseguiu.",
    "guarda.oscilacao": "AVISO: você está alternando entre as mesmas ações sem progresso. Mude de estratégia ou finalize.",
    "guarda.erros_seguidos": "AVISO: {n} erros seguidos. Leia a última mensagem de erro com atenção e corrija os argumentos.",
    "guarda.parou": "Parei porque o agente entrou em repetição (anti-loop). Progresso salvo.",
    "react.passo": "Passo {n} de no máximo {max}. Qual a próxima ação? (JSON)",
    "react.limite": "(Limite de {max} passos atingido.) Progresso:\n{resumo}",
    "react.nao_continuou": "Não consegui continuar: {erro}",
    "react.resumi": "Contexto grande: resumi {n} passo(s) antigos.",
    # json
    "json.recusado": "Sua resposta não foi aceita ({erro}). Responda de novo SOMENTE com o JSON correto, seguindo o schema.",
    "json.sem_json": "a resposta não continha um JSON válido",
    "json.instrucao": "Responda SOMENTE com um objeto JSON válido (sem texto antes ou depois, sem ```), seguindo este schema:",
    # handoff
    "handoff.iniciado": "O chat chegou a {pct}% do contexto. Resumi tudo e continuei num chat novo ({novo}), ligado ao anterior.",
    "handoff.titulo": "Continuação de: {titulo}",
    "handoff.cabecalho": "CONTINUAÇÃO AUTOMÁTICA. Este chat continua o chat anterior ({anterior}). Estado salvo:",
    # cli
    "cli.erros": "Há erros. Veja docs/SOLUCAO-DE-PROBLEMAS.md",
    "cli.ok": "Tudo certo!",
    "cli.sessao": "Sessão",
    "cli.ate_logo": "Até logo!",
    "cli.idioma_definido": "Idioma definido: {idioma}",
    "cli.api_iniciando": "API do NLR em http://{host}:{porta} (documentação em /docs)",
}

EN = {
    "app.nome": "Neuron Local Research",
    "app.descricao": "Neuron Local Research (NLR) — a research and project agent that runs on your own computer.",
    "prompt.idioma": "Always answer in English, unless the user asks for another language.",
    "modelo.auto_escolhido": "No chat model was loaded; I picked '{modelo}' from the available ones. "
                             "The server will load it now (this may take a while). To pin it, set modelo.modelo_chat in config.yaml.",
    "modelo.auto_carregado": "Using the loaded model: {modelo}",
    "modelo.emb_escolhido": "Embedding model detected: {modelo}",
    "modelo.sem_chat": "The {backend} server is up, but no chat model is available. "
                       "Download or load a model (in LM Studio: Discover/My Models tab).",
    "modelo.nao_encontrado": "Model '{modelo}' does not exist on the {backend} server. Available: {lista}",
    "modelo.contexto": "Real model context: {n} tokens (source: {fonte}).",
    "perfil.escolhido": "Profile {perfil}: up to {ferr} tools per step, {passos} steps, context {ctx} tokens.",
    "perfil.pequeno": "small",
    "perfil.medio": "medium",
    "perfil.grande": "large",
    "hw.resumo": "RAM {ram} GB | GPU: {gpu} | VRAM {vram} GB | CPUs {cpus}",
    "hw.sem_gpu": "not detected",
    "hw.recomendacao": "Recommended for this PC: models up to ~{b}B parameters (Q4_K_M quantization).",
    "ferr.inexistente": "ERROR: tool '{nome}' does not exist. Use exactly one of these names: {lista}.",
    "ferr.parecida": " Did you mean '{sugestao}'?",
    "ferr.args_invalidos": "ERROR: invalid arguments for {nome}: {erros}. Fix them and send again in this format: {formato}",
    "ferr.args_nao_objeto": "ERROR: 'argumentos' must be a JSON object, e.g. {{\"caminho\": \"a.txt\"}}.",
    "guarda.repeticao": "WARNING: you repeated the same action {n} times and the result does not change. Try another "
                        "approach or use 'finalizar' explaining what you achieved.",
    "guarda.oscilacao": "WARNING: you are alternating between the same actions without progress. Change strategy or finish.",
    "guarda.erros_seguidos": "WARNING: {n} errors in a row. Read the last error message carefully and fix the arguments.",
    "guarda.parou": "Stopped because the agent got stuck in a loop (anti-loop). Progress saved.",
    "react.passo": "Step {n} of at most {max}. What is the next action? (JSON)",
    "react.limite": "({max}-step limit reached.) Progress:\n{resumo}",
    "react.nao_continuou": "I could not continue: {erro}",
    "react.resumi": "Large context: summarized {n} old step(s).",
    "json.recusado": "Your answer was not accepted ({erro}). Answer again with ONLY the correct JSON, following the schema.",
    "json.sem_json": "the answer did not contain valid JSON",
    "json.instrucao": "Answer with ONLY a valid JSON object (no text before or after, no ```), following this schema:",
    "handoff.iniciado": "The chat reached {pct}% of the context. I summarized everything and continued in a new chat ({novo}), linked to the previous one.",
    "handoff.titulo": "Continuation of: {titulo}",
    "handoff.cabecalho": "AUTOMATIC CONTINUATION. This chat continues the previous chat ({anterior}). Saved state:",
    "cli.erros": "There are errors. See docs/SOLUCAO-DE-PROBLEMAS.md",
    "cli.ok": "All good!",
    "cli.sessao": "Session",
    "cli.ate_logo": "Bye!",
    "cli.idioma_definido": "Language set: {idioma}",
    "cli.api_iniciando": "NLR API at http://{host}:{porta} (docs at /docs)",
}


# ---------------------------------------------------------------- v0.7: visão
PT.update({
    "visao.sem_visao": ("O modelo '{modelo}' não tem visão (não aceita imagens). Como resolver:\n"
                        "  1. No LM Studio, baixe um modelo com o ícone de olho 👁 (ex.: Qwen2.5-VL 7B, Gemma 3 12B, "
                        "MiniCPM-V) e carregue-o.\n  2. No config.yaml, em modelo:, ponha modelo_visao: \"<nome do modelo>\"\n"
                        "  3. Confira com: nlr imagem status"),
    "visao.nenhum": ("O modelo de chat '{modelo}' não tem visão e não há nenhum modelo de visão no servidor. Como resolver:\n"
                     "  1. No LM Studio, aba Discover, procure 'qwen2.5-vl-7b' ou 'gemma-3-12b' (têm o ícone de olho 👁).\n"
                     "  2. Baixe, carregue e ponha o nome em modelo.modelo_visao no config.yaml.\n"
                     "  3. Confira com: nlr imagem status"),
    "visao.nao_encontrado": ("O modelo de visão '{modelo}' (modelo.modelo_visao) não existe no servidor. "
                             "Modelos com visão disponíveis: {lista}. Corrija o nome no config.yaml ou deixe vazio."),
    "visao.auto": "O modelo de chat não tem visão; para imagens vou usar '{modelo}'.",
    "visao.nao_carregado": ("O modelo de visão '{modelo}' não está carregado. O LM Studio carrega sozinho no primeiro uso "
                            "(se 'Just-in-time loading' estiver ligado) — pode demorar. Para ir mais rápido, carregue-o antes."),
    "visao.desconhecido": ("Não dá para saber pelo servidor se '{modelo}' tem visão. Se der erro, use um modelo com visão "
                           "em modelo.modelo_visao."),
    "visao.pessoas": ("A imagem parece mostrar pessoas em destaque: por privacidade, a busca reversa não foi feita "
                      "(o NLR não identifica pessoas pelo rosto). A pesquisa foi feita só pela descrição."),
    "visao.reversa_sem_chave": "Busca reversa ligada, mas falta a chave {var} no arquivo .env. Fiz só a pesquisa pela descrição.",
    "visao.reversa_sem_consentimento": ("Busca reversa (serpapi) configurada, mas visao.busca_reversa.consentimento_envio "
                                        "está false: nada foi enviado. Fiz só a pesquisa pela descrição."),
    "visao.reversa_falhou": "A busca reversa falhou ({erro}). Fiz só a pesquisa pela descrição.",
    "visao.prompt_sistema": ("Você é um analista de imagens cuidadoso e honesto. Responda em português do Brasil. "
                             "Nunca identifique pessoas pelo rosto nem diga quem elas são; descreva só aparência, roupas, cenário e ações."),
})
EN.update({
    "visao.sem_visao": ("The model '{modelo}' has no vision (it does not accept images). How to fix:\n"
                        "  1. In LM Studio, download a model with the eye icon 👁 (e.g. Qwen2.5-VL 7B, Gemma 3 12B, "
                        "MiniCPM-V) and load it.\n  2. In config.yaml, under modelo:, set modelo_visao: \"<model name>\"\n"
                        "  3. Check with: nlr imagem status"),
    "visao.nenhum": ("The chat model '{modelo}' has no vision and there is no vision model on the server. How to fix:\n"
                     "  1. In LM Studio, Discover tab, search 'qwen2.5-vl-7b' or 'gemma-3-12b' (they have the eye icon 👁).\n"
                     "  2. Download, load it and put its name in modelo.modelo_visao in config.yaml.\n"
                     "  3. Check with: nlr imagem status"),
    "visao.nao_encontrado": ("The vision model '{modelo}' (modelo.modelo_visao) does not exist on the server. "
                             "Available vision models: {lista}. Fix the name in config.yaml or leave it empty."),
    "visao.auto": "The chat model has no vision; for images I will use '{modelo}'.",
    "visao.nao_carregado": ("The vision model '{modelo}' is not loaded. LM Studio loads it on first use "
                            "(if 'Just-in-time loading' is on) — this may take a while. Load it beforehand to be faster."),
    "visao.desconhecido": ("The server does not say whether '{modelo}' has vision. If it fails, set a vision model "
                           "in modelo.modelo_visao."),
    "visao.pessoas": ("The image seems to show people prominently: for privacy, reverse search was skipped "
                      "(NLR does not identify people by their face). The search used only the description."),
    "visao.reversa_sem_chave": "Reverse search is on, but the key {var} is missing from .env. I searched by description only.",
    "visao.reversa_sem_consentimento": ("Reverse search (serpapi) is configured, but visao.busca_reversa.consentimento_envio "
                                        "is false: nothing was sent. I searched by description only."),
    "visao.reversa_falhou": "Reverse search failed ({erro}). I searched by description only.",
    "visao.prompt_sistema": ("You are a careful and honest image analyst. Answer in English. "
                             "Never identify people by their face or say who they are; describe only appearance, clothing, setting and actions."),
})
